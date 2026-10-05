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

# Buscar e importar 'paradas_horarios.py' ya sea en la raíz del repo o en una subcarpeta
def cargar_modulo_paradas():
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

# Cargar archivos base de paradas y recorridos
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
TRAZAS_GEO = {lin: {} for lin in MAPA_LINEAS.values()}
TRAZAS_DENSAS = {lin: {} for lin in MAPA_LINEAS.values()}

def distancia_km(lat1, lon1, lat2, lon2):
    return math.sqrt(((lat1 - lat2) * 111.0) ** 2 + ((lon1 - lon2) * 111.0 * 0.777) ** 2)

def densificar_traza_con_distancia(puntos, paso_km=0.020):
    """
    Subdivide la polilínea cada 20 metros y guarda en cada punto [lat, lon, km_acumulados]
    para medir la distancia real exacta siguiendo las calles del recorrido.
    """
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
HTTP_SESSION = requests.Session()
ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {},
    "contador_ids": 1,
    "idx_radar": 0,
    "ultimo_escaneo": 0.0
}
RADAR_LOCK = Lock()

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
    return int(m.group(1)) if m else 999

def filtrar_arribos_viaje_actual(arribos, linea, max_minutos=42):
    """
    Filtra los arribos devueltos por una parada testigo:
    1) Descarta predicciones a futuro (> max_minutos) que corresponden a la vuelta siguiente
       después de cambiar de cabecera.
    2) Si la misma unidad aparece dos veces en una parada compartida, conserva solo el menor tiempo.
    """
    validos = []
    for a in arribos:
        min_eta = extraer_minutos(a.get("tiempo") or a.get("tiempo_arribo"))
        if min_eta <= max_minutos:
            validos.append({**a, "_min_eta": min_eta})

    ordenados = sorted(validos, key=lambda x: x["_min_eta"])
    unicos = []
    for a in ordenados:
        try:
            lat, lon = float(a.get("lat") or 0), float(a.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        if not lat or not lon:
            continue
        if not any(distancia_km(lat, lon, float(u["lat"]), float(u["lon"])) < 0.05 for u in unicos):
            unicos.append({**a, "linea": linea})
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
    # Si conocemos el índice previo de la unidad, priorizamos continuidad hacia adelante en rulos
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
    """
    Compara en cuál de las dos trazas (IDA o VUELTA) el desplazamiento del colectivo
    representa un avance positivo sobre el kilometraje acumulado del recorrido.
    """
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
    """
    Encuentra el primer paso válido de la traza (por delante del colectivo) por la parada.
    Evita tomar la segunda pasada en recorridos con bucles o rulos.
    """
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
                # Salió del radio de la parada: nos quedamos con esta primera pasada
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

            # Evitar que dos unidades de distinto sentido en plena ruta se fusionen entre sí
            if code_bandera and b.get("sentido_code") != code_bandera:
                if not cabecera_actual and not b.get("cabecera") and dist > 0.06:
                    continue
                score = dist + 0.35
            else:
                score = dist

            if score < min_score:
                min_score, bus_match_id = score, b_id

        if bus_match_id:
            usados_en_lote.add(bus_match_id)
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            dist_avance = distancia_km(bus["lat"], bus["lon"], lat, lon)
            dt = max(ahora - bus["last_gps_at"], 1.0)

            # 1. En sectores donde las trazas de IDA y VUELTA van por distintas calles (>80m), manda la calle
            if abs(d_nqn - d_plo) > 0.08:
                sentido, sentido_code = sentido_geo, code_geo
            # 2. Si reporta bandera oficial, validamos que no sea la predicción de la vuelta siguiente
            elif sentido_bandera:
                eta_previa = bus.get("min_eta_radar", 999)
                edad_eta_previa = ahora - bus.get("eta_radar_at", 0)
                if code_bandera != bus["sentido_code"] and edad_eta_previa < 45 and min_eta > eta_previa + 4:
                    sentido, sentido_code = bus["sentido"], bus["sentido_code"]
                else:
                    sentido, sentido_code = sentido_bandera, code_bandera
                    bus["min_eta_radar"] = min_eta
                    bus["eta_radar_at"] = ahora
            # 3. Si avanzó físicamente sobre una calle compartida sin bandera, medimos el avance en la traza
            elif dist_avance > 0.025:
                sent_av, code_av = deducir_sentido_por_avance(linea, bus["lat"], bus["lon"], lat, lon)
                if code_av:
                    sentido, sentido_code = sent_av, code_av
                else:
                    sentido, sentido_code = bus["sentido"], bus["sentido_code"]
            else:
                sentido, sentido_code = bus["sentido"], bus["sentido_code"]

            if min_eta <= bus.get("min_eta_radar", 999) or (ahora - bus.get("eta_radar_at", 0)) >= 45:
                bus["min_eta_radar"] = min_eta
                bus["eta_radar_at"] = ahora

            # Solo reiniciamos last_gps_at cuando el colectivo realmente se desplazó (>12 metros)
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

    # Purga inteligente: mantiene unidades esperando en cabecera si siguen reportando, y limpia el resto
    buses_limpios = {}
    for k, v in ESTADO_GLOBAL["buses"].items():
        sin_mover = ahora - v["last_gps_at"]
        sin_ver = ahora - v.get("last_seen_at", v["last_gps_at"])
        if v.get("cabecera") and sin_ver < 150 and sin_mover < 900:
            buses_limpios[k] = v
        elif sin_mover < 480 and sin_ver < 240:
            buses_limpios[k] = v
    ESTADO_GLOBAL["buses"] = buses_limpios

def ejecutar_paso_radar(cantidad_paradas=6):
    if not RADAR_LOCK.acquire(blocking=False):
        return
    try:
        ESTADO_GLOBAL["ultimo_escaneo"] = time.time()
        paradas_radar = MOD_PARADAS.PARADAS_RADAR
        idx = ESTADO_GLOBAL["idx_radar"]
        lote = [paradas_radar[(idx + i) % len(paradas_radar)] for i in range(cantidad_paradas)]
        ESTADO_GLOBAL["idx_radar"] = (idx + cantidad_paradas) % len(paradas_radar)

        for p_id, p_cod, p_lin in lote:
            try:
                rp = HTTP_SESSION.get(
                    f"{URL_WORKER}parada",
                    params={"id": p_id, "cod": p_cod, "linea": p_lin},
                    timeout=6
                )
                if rp.status_code == 200:
                    max_min = 62 if p_lin == "50R" else 42
                    arribos_actuales = filtrar_arribos_viaje_actual(
                        rp.json().get("arribos", []), p_lin, max_minutos=max_min
                    )
                    procesar_nuevas_posiciones(arribos_actuales)
            except Exception:
                pass

        try:
            ESTADO_GLOBAL["timestamp"] = datetime.now(
                zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
            ).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")
    finally:
        RADAR_LOCK.release()

def recolector_fondo():
    while True:
        ejecutar_paso_radar(6)
        time.sleep(8)

Thread(target=recolector_fondo, daemon=True).start()

@app.route('/ok')
@app.route('/cron')
@app.route('/ping')
def ruta_cron_ok():
    if time.time() - ESTADO_GLOBAL.get("ultimo_escaneo", 0) > 4:
        Thread(target=ejecutar_paso_radar, args=(8,), daemon=True).start()
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
    if not p_id_raw or not p_linea:
        return jsonify({"arribos": []})

    ids_consulta = [x.strip() for x in re.split(r'[,/]', p_id_raw) if x.strip()]
    coords_parada = [MAPA_COORDS_PARADAS[pid] for pid in ids_consulta if pid in MAPA_COORDS_PARADAS]
    if not coords_parada:
        return jsonify({"arribos": []})

    ahora = time.time()
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
    # Si no hay colectivos en memoria (ej. recién despierta Render), escanea en el acto
    if not ESTADO_GLOBAL["buses"] and (ahora - ESTADO_GLOBAL.get("ultimo_escaneo", 0)) > 2:
        ejecutar_paso_radar(8)
    # Si el hilo de fondo demoró más de 7 segundos, lanza un barrido asíncrono
    elif (ahora - ESTADO_GLOBAL.get("ultimo_escaneo", 0)) > 7:
        Thread(target=ejecutar_paso_radar, args=(6,), daemon=True).start()

    ahora = time.time()
    lista = [
        {**b, "edad_senal": int(max(0, ahora - b["last_gps_at"]))}
        for b in ESTADO_GLOBAL["buses"].values()
    ]
    return jsonify({"timestamp": ESTADO_GLOBAL["timestamp"], "buses": lista, "total_buses": len(lista)})

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
