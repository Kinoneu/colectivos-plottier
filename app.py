import os
import re
import sys
import time
import json
import math
import requests
import importlib.util
from datetime import datetime
import zoneinfo
from threading import Thread, Lock
from flask import Flask, jsonify, render_template_string, request, send_file, Response

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

# Carga de catálogos y planillas priorizando la carpeta 'paradas-horarios'
def cargar_modulo_paradas():
    ruta_pref = os.path.join(BASE_DIR, "paradas-horarios", "paradas_horarios.py")
    if os.path.isfile(ruta_pref):
        spec = importlib.util.spec_from_file_location("paradas_horarios", ruta_pref)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["paradas_horarios"] = mod
        spec.loader.exec_module(mod)
        return mod

    for root, _, files in os.walk(BASE_DIR):
        if "paradas_horarios.py" in files:
            ruta_mod = os.path.join(root, "paradas_horarios.py")
            spec = importlib.util.spec_from_file_location("paradas_horarios", ruta_mod)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["paradas_horarios"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError("No se encontró paradas_horarios.py en el repositorio.")

MOD_PARADAS = cargar_modulo_paradas()

with open(os.path.join(BASE_DIR, "paradas_optimizadas.json"), "r", encoding="utf-8") as f:
    PARADAS_RAW = json.load(f)

with open(os.path.join(BASE_DIR, "urbano y r.json"), "r", encoding="utf-8") as f:
    raw_recorridos = json.load(f)["DBCuandoLlega"]["recorridos"]

MAPA_LINEAS = {
    "1013": "50A",
    "1014": "50B",
    "1015": "50R",
    "1109": "URBANO",
    "1079": "52 CENTRO",
    "1080": "52 UNION"
}
CODIGO_POR_LINEA = {v: k for k, v in MAPA_LINEAS.items()}
TRAZAS_GEO = {lin: {} for lin in MAPA_LINEAS.values()}
TRAZAS_DENSAS = {lin: {} for lin in MAPA_LINEAS.values()}

def distancia_km(lat1, lon1, lat2, lon2):
    return math.sqrt(((lat1 - lat2) * 111.0) ** 2 + ((lon1 - lon2) * 111.0 * 0.777) ** 2)

def densificar_traza_con_distancia(puntos, paso_km=0.020):
    if not puntos or len(puntos) < 2:
        return []
    acum_km = 0.0
    res = [[puntos[0][0], puntos[0][1], 0.0]]
    for i in range(len(puntos) - 1):
        p1, p2 = puntos[i], puntos[i + 1]
        d_seg = distancia_km(p1[0], p1[1], p2[0], p2[1])
        if d_seg < 0.0005:
            continue
        pasos = max(1, int(math.ceil(d_seg / paso_km)))
        delta_d = d_seg / pasos
        for s in range(1, pasos + 1):
            t = s / pasos
            acum_km += delta_d
            res.append([
                round(p1[0] + (p2[0] - p1[0]) * t, 6),
                round(p1[1] + (p2[1] - p1[1]) * t, 6),
                round(acum_km, 4)
            ])
    return res

for rec in raw_recorridos:
    cod = str(rec.get("codigoLinea"))
    lin = MAPA_LINEAS.get(cod)
    if not lin:
        continue
    sentido = "HACIA_NEUQUEN" if "IDA" in rec.get("bandera", "").upper() else "HACIA_PLOTTIER"
    pts = [
        [round(float(p["latitud"]), 6), round(float(p["longitud"]), 6)]
        for p in rec.get("puntos", [])
        if p.get("latitud") and p.get("longitud")
    ]
    TRAZAS_GEO[lin][sentido] = pts
    TRAZAS_DENSAS[lin][sentido] = densificar_traza_con_distancia(pts)

MAPA_COORDS_PARADAS = {str(p[0]).strip(): (float(p[1]), float(p[2])) for p in PARADAS_RAW}
PARADAS_CLUSTERIZADAS = MOD_PARADAS.agrupar_paradas_inteligente(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"

# Sesión exclusiva para consultar al Worker (envía UA para evitar bloqueo interno)
WORKER_SESSION = requests.Session()
WORKER_SESSION.headers.update({
    "User-Agent": BROWSER_UA,
    "Accept": "application/json"
})

ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {},
    "contador_ids": 1,
    "idx_radar": 0,
    "ultimo_escaneo": 0.0,
    "ultimo_diag": "Iniciando..."
}
RADAR_LOCK = Lock()

# Paradas terminales que agrupan a todos los colectivos activos
PARADAS_RADAR_DIRECTO = [
    ("NV 2574", "1013", "50A"),
    ("NV4120", "1013", "50A"),
    ("NV 2574", "1014", "50B"),
    ("NV4120", "1014", "50B"),
    ("NV 4998", "1015", "50R"),
    ("NV6001", "1015", "50R"),
    ("NV8064", "1109", "URBANO"),
    ("51 00001", "1109", "URBANO"),
    ("5200001", "1079", "52 CENTRO"),
    ("5200047", "1079", "52 CENTRO"),
    ("5200001", "1080", "52 UNION"),
    ("5200047", "1080", "52 UNION")
]

def consultar_worker(p_id, p_cod, p_lin):
    """
    Delega 100% de la carga al Worker de Cloudflare, que elude los bloqueos de Indalo.
    """
    try:
        rp = WORKER_SESSION.get(
            f"{URL_WORKER}parada",
            params={"id": p_id, "cod": p_cod, "linea": p_lin},
            timeout=8
        )
        if rp.status_code == 200:
            payload = rp.json()
            if payload.get("ok"):
                arribos = payload.get("arribos") or []
                ESTADO_GLOBAL["ultimo_diag"] = f"Worker OK: {p_lin} en {p_id} ({len(arribos)} uni)"
                return arribos
            else:
                ESTADO_GLOBAL["ultimo_diag"] = f"Worker err lógico: {payload.get('error')}"
        else:
            ESTADO_GLOBAL["ultimo_diag"] = f"Worker bloqueado: HTTP {rp.status_code}"
    except Exception as e:
        ESTADO_GLOBAL["ultimo_diag"] = f"Worker Timeout/Exc: {str(e)[:40]}"
    return []

def detectar_cabecera(lat, lon):
    for c_lat, c_lon, c_nom in MOD_PARADAS.CABECERAS_GEO:
        if distancia_km(lat, lon, c_lat, c_lon) <= 0.35:
            return c_nom
    return None

def normalizar_linea(linea_raw):
    lin = str(linea_raw or "").upper().strip()
    if "51" in lin or "URBANO" in lin: return "URBANO"
    if "50A" in lin or "50 A" in lin: return "50A"
    if "50B" in lin or "50 B" in lin: return "50B"
    if "50R" in lin or "50 R" in lin: return "50R"
    if "UNION" in lin: return "52 UNION"
    if "52" in lin: return "52 CENTRO"
    return lin

def formatear_sentido_humano(linea, sentido_code):
    if linea == "URBANO":
        return "Hacia Centro / ETOP" if sentido_code == "HACIA_NEUQUEN" else "Hacia Las Lilas"
    if linea in ("52 CENTRO", "52 UNION"):
        return "Hacia B° Unión / R. Colorado" if sentido_code == "HACIA_NEUQUEN" else "Hacia Terminal ETOP"
    if linea == "50R":
        return "Hacia Neuquén" if sentido_code == "HACIA_NEUQUEN" else "Hacia El Mangrullo"
    return "Hacia Neuquén" if sentido_code == "HACIA_NEUQUEN" else "Hacia Plottier"

def extraer_minutos(tiempo_str):
    txt = str(tiempo_str or "").upper()
    if any(k in txt for k in ("LLEGANDO", "AHORA", "PARADA", "PROX", "PRÓX", "MENOS")):
        return 0
    m = re.search(r'(\d+)', txt)
    return int(m.group(1)) if m else 35

def filtrar_arribos_viaje_actual(arribos, linea, max_minutos=150):
    validos = []
    for a in arribos:
        min_eta = extraer_minutos(a.get("tiempo") or a.get("tiempo_arribo"))
        if min_eta <= max_minutos:
            es_prim = 0 if a.get("_es_primario") else 1
            validos.append({**a, "_min_eta": min_eta, "_orden_prim": es_prim})

    ordenados = sorted(validos, key=lambda x: (x["_min_eta"], x["_orden_prim"]))
    unicos = []
    for a in ordenados:
        try:
            lat = float(str(a.get("lat") or 0).replace(",", "."))
            lon = float(str(a.get("lon") or 0).replace(",", "."))
        except (ValueError, TypeError):
            continue
        if not lat or not lon:
            continue
        if not any(distancia_km(lat, lon, float(u["lat"]), float(u["lon"])) < 0.05 for u in unicos):
            unicos.append({**a, "lat": lat, "lon": lon, "linea": linea})
    return unicos

def deducir_sentido_bandera(ramal_raw, linea=""):
    txt = str(ramal_raw or "").upper()
    if "VUELTA" in txt or "VTA" in txt:
        return formatear_sentido_humano(linea, "HACIA_PLOTTIER"), "HACIA_PLOTTIER"
    if "IDA" in txt:
        return formatear_sentido_humano(linea, "HACIA_NEUQUEN"), "HACIA_NEUQUEN"
    return None, None

def indice_mas_cercano(lat, lon, traza, idx_previo=None):
    if not traza:
        return 0, 999.0
    if idx_previo is not None and 0 <= idx_previo < len(traza):
        inicio = max(0, idx_previo - 4)
        fin = min(len(traza), idx_previo + 35)
        mejor_local, menor_d_local = idx_previo, 999.0
        for i in range(inicio, fin):
            d = distancia_km(lat, lon, traza[i][0], traza[i][1])
            if d < menor_d_local:
                menor_d_local = d
                mejor_local = i
        if menor_d_local <= 0.12:
            return mejor_local, menor_d_local

    mejor_idx, menor_d = 0, 999.0
    for i, pt in enumerate(traza):
        d = distancia_km(lat, lon, pt[0], pt[1])
        if d < menor_d:
            menor_d = d
            mejor_idx = i
    return mejor_idx, menor_d

def deducir_sentido_geometria(linea, lat, lon):
    pts_nqn = TRAZAS_DENSAS.get(linea, {}).get("HACIA_NEUQUEN", [])
    pts_plo = TRAZAS_DENSAS.get(linea, {}).get("HACIA_PLOTTIER", [])
    _, d_nqn = indice_mas_cercano(lat, lon, pts_nqn)
    _, d_plo = indice_mas_cercano(lat, lon, pts_plo)
    if d_plo < d_nqn:
        return formatear_sentido_humano(linea, "HACIA_PLOTTIER"), "HACIA_PLOTTIER", d_nqn, d_plo
    return formatear_sentido_humano(linea, "HACIA_NEUQUEN"), "HACIA_NEUQUEN", d_nqn, d_plo

def deducir_sentido_por_avance(linea, prev_lat, prev_lon, lat, lon):
    mejor_code = None
    mayor_avance = 0.0
    for code in ("HACIA_NEUQUEN", "HACIA_PLOTTIER"):
        traza = TRAZAS_DENSAS.get(linea, {}).get(code, [])
        if len(traza) < 2:
            continue
        idx1, d1 = indice_mas_cercano(prev_lat, prev_lon, traza)
        idx2, d2 = indice_mas_cercano(lat, lon, traza, idx_previo=idx1)
        if d1 <= 0.15 and d2 <= 0.15:
            avance_km = traza[idx2][2] - traza[idx1][2]
            if avance_km > mayor_avance:
                mayor_avance = avance_km
                mejor_code = code
    if mejor_code and mayor_avance >= 0.025:
        return formatear_sentido_humano(linea, mejor_code), mejor_code
    return None, None

def encontrar_indice_parada_adelante(coords_parada, traza, idx_bus):
    mejor_idx_stop, menor_d_stop = -1, 999.0
    for (plat, plon) in coords_parada:
        umbral_km = 0.22 if plon > -68.088 else 0.065
        en_zona = False
        idx_pasada, d_pasada = -1, 999.0
        for i in range(max(0, idx_bus - 2), len(traza)):
            pt = traza[i]
            d = distancia_km(plat, plon, pt[0], pt[1])
            if d <= umbral_km:
                en_zona = True
                if d < d_pasada:
                    d_pasada = d
                    idx_pasada = i
            elif en_zona:
                break

        if idx_pasada != -1:
            if mejor_idx_stop == -1 or idx_pasada < mejor_idx_stop:
                mejor_idx_stop = idx_pasada
                menor_d_stop = d_pasada
    return mejor_idx_stop, menor_d_stop

def formatear_rango_arribo(dist_recorrido_km, lon_bus=-68.18):
    if dist_recorrido_km <= 0.18:
        return "Llegando (< 1 min)", 0

    vel_comercial = 26.5 if -68.215 <= lon_bus <= -68.095 else 23.0
    min_base = max(1, int(round((dist_recorrido_km / vel_comercial) * 60)))
    min_rapido = max(1, min_base - 1) if min_base > 2 else min_base
    margen = 2 if min_base <= 5 else (3 if min_base <= 18 else 4)
    min_lento = min_rapido + margen
    return f"Entre {min_rapido} y {min_lento} min", min_rapido

def procesar_nuevas_posiciones(detecciones):
    ahora = time.time()
    usados_en_lote = set()

    for d in detecciones:
        try:
            lat, lon = float(d.get("lat") or 0), float(d.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        linea = normalizar_linea(d.get("linea"))
        if not lat or not lon or not linea:
            continue

        min_eta = int(d.get("_min_eta") or extraer_minutos(d.get("tiempo") or d.get("tiempo_arribo")))
        sentido_bandera, code_bandera = deducir_sentido_bandera(d.get("ramal"), linea)
        sentido_geo, code_geo, d_nqn, d_plo = deducir_sentido_geometria(linea, lat, lon)
        cabecera_actual = detectar_cabecera(lat, lon)

        bus_match_id, min_score = None, 1.4
        for b_id, b in ESTADO_GLOBAL["buses"].items():
            if b_id in usados_en_lote or b["linea"] != linea:
                continue
            dist = distancia_km(b["lat"], b["lon"], lat, lon)
            if dist > 1.4:
                continue

            if code_bandera and b.get("sentido_code") != code_bandera:
                if not cabecera_actual and not b.get("cabecera") and dist > 0.08:
                    continue
                score = dist + 0.30
            else:
                score = dist

            if score < min_score:
                min_score, bus_match_id = score, b_id

        if bus_match_id:
            usados_en_lote.add(bus_match_id)
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            dist_avance = distancia_km(bus["lat"], bus["lon"], lat, lon)
            dt = max(ahora - bus["last_gps_at"], 1.0)

            if abs(d_nqn - d_plo) > 0.08:
                sentido, sentido_code = sentido_geo, code_geo
            elif sentido_bandera:
                eta_previa = bus.get("min_eta_radar", 999)
                edad_eta_previa = ahora - bus.get("eta_radar_at", 0)
                if code_bandera != bus["sentido_code"] and edad_eta_previa < 35 and min_eta > eta_previa + 4:
                    sentido, sentido_code = bus["sentido"], bus["sentido_code"]
                else:
                    sentido, sentido_code = sentido_bandera, code_bandera
                    bus["min_eta_radar"] = min_eta
                    bus["eta_radar_at"] = ahora
            elif dist_avance > 0.025:
                sent_av, code_av = deducir_sentido_por_avance(linea, bus["lat"], bus["lon"], lat, lon)
                if code_av:
                    sentido, sentido_code = sent_av, code_av
                else:
                    sentido, sentido_code = bus["sentido"], bus["sentido_code"]
            else:
                sentido, sentido_code = bus["sentido"], bus["sentido_code"]

            if min_eta <= bus.get("min_eta_radar", 999) or (ahora - bus.get("eta_radar_at", 0)) >= 35:
                bus["min_eta_radar"] = min_eta
                bus["eta_radar_at"] = ahora

            if dist_avance > 0.012:
                vel_kmh = round(max(18.0, min((dist_avance / dt) * 3600.0, 45.0)), 1)
                traza_act = TRAZAS_DENSAS.get(linea, {}).get(sentido_code, [])
                nuevo_idx, _ = indice_mas_cercano(lat, lon, traza_act, bus.get("traza_idx"))
                bus.update({
                    "prev_lat": bus["lat"],
                    "prev_lon": bus["lon"],
                    "lat": lat,
                    "lon": lon,
                    "vel_kmh": vel_kmh,
                    "traza_idx": nuevo_idx,
                    "last_gps_at": ahora
                })

            ramal_actual = str(d.get("ramal") or bus.get("ramal") or f"Línea {linea}")
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("VUELTA", "IDA")

            bus.update({
                "ramal": ramal_actual,
                "sentido": sentido,
                "sentido_code": sentido_code,
                "cabecera": cabecera_actual,
                "last_seen_at": ahora,
                "updated_at": ahora
            })
        else:
            nuevo_id = f"{linea}_{ESTADO_GLOBAL['contador_ids']}"
            ESTADO_GLOBAL["contador_ids"] += 1
            usados_en_lote.add(nuevo_id)

            if abs(d_nqn - d_plo) > 0.06:
                sentido, sentido_code = sentido_geo, code_geo
            elif sentido_bandera:
                sentido, sentido_code = sentido_bandera, code_bandera
            else:
                sentido_code = code_geo or "HACIA_PLOTTIER"
                sentido = formatear_sentido_humano(linea, sentido_code)

            ramal_inicial = str(d.get("ramal") or f"Línea {linea}")
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in ramal_inicial.upper():
                ramal_inicial = ramal_inicial.replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in ramal_inicial.upper():
                ramal_inicial = ramal_inicial.replace("VUELTA", "IDA")

            traza_ini = TRAZAS_DENSAS.get(linea, {}).get(sentido_code, [])
            idx_ini, _ = indice_mas_cercano(lat, lon, traza_ini)

            ESTADO_GLOBAL["buses"][nuevo_id] = {
                "id": nuevo_id,
                "linea": linea,
                "ramal": ramal_inicial,
                "sentido": sentido,
                "sentido_code": sentido_code,
                "lat": lat,
                "lon": lon,
                "prev_lat": lat,
                "prev_lon": lon,
                "traza_idx": idx_ini,
                "vel_kmh": 28.0,
                "min_eta_radar": min_eta,
                "eta_radar_at": ahora,
                "cabecera": cabecera_actual,
                "last_gps_at": ahora,
                "last_seen_at": ahora,
                "updated_at": ahora
            }

    buses_limpios = {}
    for k, v in ESTADO_GLOBAL["buses"].items():
        sin_mover = ahora - v["last_gps_at"]
        sin_ver = ahora - v.get("last_seen_at", v["last_gps_at"])
        if v.get("cabecera") and sin_ver < 180 and sin_mover < 900:
            buses_limpios[k] = v
        elif sin_mover < 480 and sin_ver < 260:
            buses_limpios[k] = v
    ESTADO_GLOBAL["buses"] = buses_limpios

def ejecutar_paso_radar(cantidad_paradas=6):
    if not RADAR_LOCK.acquire(blocking=False):
        return
    try:
        ESTADO_GLOBAL["ultimo_escaneo"] = time.time()
        idx = ESTADO_GLOBAL["idx_radar"]
        lote = [PARADAS_RADAR_DIRECTO[(idx + i) % len(PARADAS_RADAR_DIRECTO)] for i in range(cantidad_paradas)]
        ESTADO_GLOBAL["idx_radar"] = (idx + cantidad_paradas) % len(PARADAS_RADAR_DIRECTO)

        acumulado_por_linea = {}
        for p_id, p_cod, p_lin in lote:
            arribos_raw = consultar_worker(p_id, p_cod, p_lin)
            if arribos_raw:
                acumulado_por_linea.setdefault(p_lin, []).extend(arribos_raw)
            time.sleep(0.15)

        for lin, lista_raw in acumulado_por_linea.items():
            arribos_unicos = filtrar_arribos_viaje_actual(lista_raw, lin, max_minutos=150)
            procesar_nuevas_posiciones(arribos_unicos)

        try:
            ESTADO_GLOBAL["timestamp"] = datetime.now(
                zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
            ).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")
    finally:
        RADAR_LOCK.release()

def recolector_fondo():
    ejecutar_paso_radar(len(PARADAS_RADAR_DIRECTO))
    while True:
        time.sleep(6)
        ejecutar_paso_radar(6)

Thread(target=recolector_fondo, daemon=True).start()

@app.route('/ok')
@app.route('/cron')
@app.route('/ping')
def ruta_cron_ok():
    if time.time() - ESTADO_GLOBAL.get("ultimo_escaneo", 0) > 4:
        Thread(target=ejecutar_paso_radar, args=(6,), daemon=True).start()
    return Response("<!DOCTYPE html><html><body style='background:#fff;color:#000;'>ok</body></html>", status=200, mimetype='text/html')

@app.route('/logo.png')
@app.route('/favicon.ico')
def logo_sitio():
    for nombre in ["logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.ico", "Logo.png", "Logo.jpg"]:
        ruta = os.path.join(BASE_DIR, nombre)
        if os.path.isfile(ruta):
            return send_file(ruta)
    return ("", 404)

@app.route('/foto_perfil')
def foto_perfil():
    for nombre in ["perfil.jpg", "perfil.png", "perfil.jpeg", "perfil.webp", "Perfil.jpg", "Perfil.png"]:
        ruta = os.path.join(BASE_DIR, nombre)
        if os.path.isfile(ruta):
            return send_file(ruta)
    return ("", 404)

@app.route('/api/parada')
def api_parada():
    p_id_raw = request.args.get("id", "")
    p_linea = normalizar_linea(request.args.get("linea", ""))
    p_cod = request.args.get("cod", "") or CODIGO_POR_LINEA.get(p_linea, "1013")
    if not p_id_raw or not p_linea:
        return jsonify({"arribos": []})

    ids_consulta = [x.strip() for x in re.split(r'[,/]', p_id_raw) if x.strip()]
    coords_parada = [MAPA_COORDS_PARADAS[pid] for pid in ids_consulta if pid in MAPA_COORDS_PARADAS]

    ahora = time.time()
    buses_linea = [
        b for b in ESTADO_GLOBAL["buses"].values()
        if b["linea"] == p_linea and (ahora - b["last_gps_at"]) <= 240
    ]

    # Si no hay unidades activas, fuerza la consulta en el acto vía Worker
    if not buses_linea and ids_consulta:
        for pid_unico in ids_consulta[:2]:
            nuevos = consultar_worker(pid_unico, p_cod, p_linea)
            if nuevos:
                filtrados = filtrar_arribos_viaje_actual(nuevos, p_linea, max_minutos=150)
                procesar_nuevas_posiciones(filtrados)
                break
        ahora = time.time()

    if not coords_parada:
        return jsonify({"arribos": []})

    arribos_calculados = []
    for bus in ESTADO_GLOBAL["buses"].values():
        if bus["linea"] != p_linea or (ahora - bus["last_gps_at"]) > 240:
            continue

        sentido_code = bus["sentido_code"]
        traza = TRAZAS_DENSAS.get(p_linea, {}).get(sentido_code, [])
        if len(traza) < 2:
            continue

        idx_bus, dist_bus_traza = indice_mas_cercano(
            bus["lat"], bus["lon"], traza, bus.get("traza_idx")
        )
        limite_desvio_bus = 0.65 if bus["lon"] > -68.088 else 0.25
        if dist_bus_traza > limite_desvio_bus:
            continue

        idx_stop, _ = encontrar_indice_parada_adelante(coords_parada, traza, idx_bus)
        if idx_stop == -1:
            continue

        dist_recorrido_km = max(0.0, traza[idx_stop][2] - traza[idx_bus][2])
        if dist_recorrido_km > 25.0:
            continue

        tiempo_txt, min_orden = formatear_rango_arribo(dist_recorrido_km, bus["lon"])
        arribos_calculados.append({
            "ramal": bus["ramal"],
            "sentido": bus["sentido"],
            "tiempo": tiempo_txt,
            "lat": bus["lat"],
            "lon": bus["lon"],
            "_min": min_orden
        })

    arribos_calculados.sort(key=lambda x: x["_min"])
    return jsonify({"arribos": arribos_calculados[:4]})

@app.route('/api/radar')
def api_radar():
    ahora = time.time()
    if not ESTADO_GLOBAL["buses"] and (ahora - ESTADO_GLOBAL.get("ultimo_escaneo", 0)) > 2:
        ejecutar_paso_radar(len(PARADAS_RADAR_DIRECTO))
    elif (ahora - ESTADO_GLOBAL.get("ultimo_escaneo", 0)) > 7:
        Thread(target=ejecutar_paso_radar, args=(6,), daemon=True).start()

    ahora = time.time()
    lista = [
        {**b, "edad_senal": int(max(0, ahora - b["last_gps_at"]))}
        for b in ESTADO_GLOBAL["buses"].values()
    ]
    return jsonify({"timestamp": ESTADO_GLOBAL["timestamp"], "buses": lista, "total_buses": len(lista)})

@app.route('/api/debug_radar')
def api_debug_radar():
    prueba = consultar_worker("NV 2574", "1013", "50A")
    if prueba:
        procesar_nuevas_posiciones(filtrar_arribos_viaje_actual(prueba, "50A", max_minutos=150))
    return jsonify({
        "timestamp": ESTADO_GLOBAL["timestamp"],
        "ultimo_diag": ESTADO_GLOBAL.get("ultimo_diag"),
        "arribos_crudos_nv2574": len(prueba),
        "total_buses_en_memoria": len(ESTADO_GLOBAL["buses"]),
        "buses": list(ESTADO_GLOBAL["buses"].values())
    })

@app.route('/api/static_data')
def api_static_data():
    return jsonify({
        "trazas": TRAZAS_GEO,
        "paradas": PARADAS_CLUSTERIZADAS,
        "horarios_oficiales": MOD_PARADAS.obtener_horarios_oficiales()
    })

@app.route('/')
def home():
    base_url = request.host_url.rstrip('/')
    if base_url.startswith("http://") and "localhost" not in base_url and "127.0.0.1" not in base_url:
        base_url = base_url.replace("http://", "https://", 1)
    return render_template_string(MOD_PARADAS.HTML_COMPLETO, base_url=base_url)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
