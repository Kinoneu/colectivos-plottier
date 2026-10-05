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
MAPA_CODIGOS_LINEA = {v: k for k, v in MAPA_LINEAS.items()}

TRAZAS_GEO = {lin: {} for lin in MAPA_LINEAS.values()}
TRAZAS_DENSAS = {lin: {} for lin in MAPA_LINEAS.values()}
PARADAS_POR_SENTIDO = {lin: {"HACIA_NEUQUEN": [], "HACIA_PLOTTIER": []} for lin in MAPA_LINEAS.values()}

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

def indice_mas_cercano(lat, lon, traza):
    mejor_idx, menor_d = 0, 999.0
    for i, pt in enumerate(traza):
        d = distancia_km(lat, lon, pt[0], pt[1])
        if d < menor_d:
            menor_d = d
            mejor_idx = i
    return mejor_idx, menor_d

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

# Indexar todas las paradas ordenadas por kilómetro sobre cada traza para el Rescate Dirigido
for p in PARADAS_RAW:
    id_p = str(p[0]).strip()
    plat, plon = float(p[1]), float(p[2])
    lineas_p = p[4] or {}
    for lin_nom, lin_cod in lineas_p.items():
        if lin_nom not in TRAZAS_DENSAS:
            continue
        for sent_code, traza in TRAZAS_DENSAS[lin_nom].items():
            if not traza:
                continue
            idx_pt, d_traza = indice_mas_cercano(plat, plon, traza)
            if d_traza <= 0.075:
                PARADAS_POR_SENTIDO[lin_nom][sent_code].append({
                    "id": id_p,
                    "cod": str(lin_cod),
                    "linea": lin_nom,
                    "lat": plat,
                    "lon": plon,
                    "km": traza[idx_pt][2]
                })

for lin_nom in PARADAS_POR_SENTIDO:
    for sent_code in PARADAS_POR_SENTIDO[lin_nom]:
        PARADAS_POR_SENTIDO[lin_nom][sent_code].sort(key=lambda x: x["km"])

MAPA_COORDS_PARADAS = {str(p[0]).strip(): (float(p[1]), float(p[2])) for p in PARADAS_RAW}
PARADAS_CLUSTERIZADAS = MOD_PARADAS.agrupar_paradas_inteligente(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"
ESTADO_GLOBAL = {"timestamp": "--:--:--", "buses": {}, "contador_ids": 1, "idx_radar": 0, "ultimo_escaneo": 0.0}
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

def extraer_minutos(tiempo_str):
    m = re.search(r'(\d+)', str(tiempo_str or ""))
    return int(m.group(1)) if m else 999

def filtrar_arribos_viaje_actual(arribos, linea, max_minutos=42):
    """
    Filtra los arribos devueltos por una parada:
    1) Descarta predicciones lejanas (> 42 min) que corresponden a la vuelta siguiente.
    2) Deduplica unidades que estén a menos de 110 metros entre sí dentro de la misma respuesta.
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
        if not any(distancia_km(lat, lon, float(u["lat"]), float(u["lon"])) < 0.11 for u in unicos):
            unicos.append({**a, "linea": linea})
    return unicos

def deducir_sentido_bandera(ramal_raw):
    txt = str(ramal_raw or "").upper()
    if "VUELTA" in txt or "VTA" in txt: return "Hacia Plottier", "HACIA_PLOTTIER"
    if "IDA" in txt: return "Hacia Neuquén", "HACIA_NEUQUEN"
    return None, None

def deducir_sentido_geometria(linea, lat, lon):
    pts_nqn = TRAZAS_DENSAS.get(linea, {}).get("HACIA_NEUQUEN", [])
    pts_plo = TRAZAS_DENSAS.get(linea, {}).get("HACIA_PLOTTIER", [])
    d_nqn = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_nqn], default=99)
    d_plo = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_plo], default=99)
    if d_plo < d_nqn:
        return "Hacia Plottier", "HACIA_PLOTTIER", d_nqn, d_plo
    return "Hacia Neuquén", "HACIA_NEUQUEN", d_nqn, d_plo

def estimar_posicion_proyectada(bus, ahora):
    """
    Calcula dónde debería estar hoy un colectivo que perdió señal hace 'dt' segundos
    avanzando sobre su traza. Permite emparejarlo con exactitud cuando reaparece más adelante.
    """
    dt = max(0.0, min(ahora - bus["last_gps_at"], 180.0))
    if dt < 10.0 or bus.get("cabecera"):
        return bus["lat"], bus["lon"]

    traza = TRAZAS_DENSAS.get(bus["linea"], {}).get(bus["sentido_code"], [])
    if len(traza) < 2:
        return bus["lat"], bus["lon"]

    idx_b, dist_b = indice_mas_cercano(bus["lat"], bus["lon"], traza)
    if dist_b > 0.25:
        return bus["lat"], bus["lon"]

    # Estimar avance conservador a ~23 km/h durante el tiempo sin señal
    avance_km = (dt / 3600.0) * 23.0
    km_objetivo = traza[idx_b][2] + avance_km
    for i in range(idx_b, len(traza)):
        if traza[i][2] >= km_objetivo:
            return traza[i][0], traza[i][1]
    return traza[-1][0], traza[-1][1]

def buscar_parada_rescate(bus, ahora):
    """
    Cuando un colectivo pierde señal, selecciona quirúrgicamente una parada que esté
    entre 0.35 km y 4.2 km ADELANTE de su ubicación estimada sobre su misma ruta y sentido.
    Si el primer intento no lo encontró, rota entre las siguientes paradas hacia adelante.
    """
    linea = bus["linea"]
    sentido_code = bus["sentido_code"]
    cod_linea = MAPA_CODIGOS_LINEA.get(linea)
    if not cod_linea:
        return None

    traza = TRAZAS_DENSAS.get(linea, {}).get(sentido_code, [])
    paradas_sentido = PARADAS_POR_SENTIDO.get(linea, {}).get(sentido_code, [])
    intento = int(bus.get("intentos_rescate", 0))

    if len(traza) >= 2 and paradas_sentido:
        lat_proy, lon_proy = estimar_posicion_proyectada(bus, ahora)
        idx_proy, _ = indice_mas_cercano(lat_proy, lon_proy, traza)
        km_actual = traza[idx_proy][2]

        # Buscar paradas que estén entre 350m y 4.2km adelante del colectivo
        candidatas = [
            p for p in paradas_sentido
            if (km_actual + 0.35) <= p["km"] <= (km_actual + 4.2)
            and (p["id"].upper().startswith("NV") or p["id"].upper().startswith("N") or p["id"].startswith("5"))
        ]
        if not candidatas:
            candidatas = [p for p in paradas_sentido if p["km"] > km_actual + 0.15]

        if candidatas:
            elegida = candidatas[min(intento * 2, len(candidatas) - 1)]
            return {"id": elegida["id"], "cod": elegida["cod"], "linea": linea}

    # Respaldo si no hay paradas indexadas adelante: usar la cabecera de destino de ese sentido
    for p_id, p_cod, p_lin in MOD_PARADAS.PARADAS_RADAR:
        if p_lin == linea:
            return {"id": p_id, "cod": p_cod, "linea": p_lin}
    return None

def fusionar_buses_solapados():
    """
    CAPA 3 ANTI-SOLAPAMIENTO:
    Revisa todas las unidades activas y fusiona cualquier par de colectivos de la misma línea
    que hayan quedado solapados (< 120m en cualquier caso, o < 240m en el mismo sentido cuando
    uno tenía señal vieja y fue re-detectado más adelante).
    Conserva siempre el ID más antiguo para que el marcador del mapa no parpadee.
    """
    buses_dict = ESTADO_GLOBAL["buses"]
    ids = sorted(buses_dict.keys(), key=lambda x: int(x.split("_")[1]) if "_" in x and x.split("_")[1].isdigit() else 9999)
    eliminar = set()

    for i in range(len(ids)):
        id_a = ids[i]
        if id_a in eliminar or id_a not in buses_dict:
            continue
        a = buses_dict[id_a]

        for j in range(i + 1, len(ids)):
            id_b = ids[j]
            if id_b in eliminar or id_b not in buses_dict:
                continue
            b = buses_dict[id_b]

            if a["linea"] != b["linea"]:
                continue

            dist_real = distancia_km(a["lat"], a["lon"], b["lat"], b["lon"])
            mismo_sentido = (a["sentido_code"] == b["sentido_code"])
            diferencia_tiempo = abs(a["last_gps_at"] - b["last_gps_at"])

            # Si están prácticamente encima (< 120m) o son el mismo coche tras recuperar señal (< 240m)
            if dist_real < 0.12 or (mismo_sentido and dist_real < 0.24 and diferencia_tiempo > 12):
                if b["last_gps_at"] >= a["last_gps_at"]:
                    a.update({
                        "lat": b["lat"],
                        "lon": b["lon"],
                        "prev_lat": a["lat"],
                        "prev_lon": a["lon"],
                        "sentido": b["sentido"],
                        "sentido_code": b["sentido_code"],
                        "ramal": b["ramal"],
                        "vel_kmh": b.get("vel_kmh", a.get("vel_kmh", 28.0)),
                        "last_gps_at": b["last_gps_at"],
                        "updated_at": b["updated_at"],
                        "intentos_rescate": 0
                    })
                eliminar.add(id_b)

    for k in eliminar:
        buses_dict.pop(k, None)

def procesar_nuevas_posiciones(detecciones):
    if not detecciones:
        return
    ahora = time.time()

    # CAPA 1: Deduplicar detecciones entrantes del mismo lote que estén a menos de 110m
    lote_limpio = []
    for d in detecciones:
        try:
            lat, lon = float(d.get("lat") or 0), float(d.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        linea = normalizar_linea(d.get("linea"))
        if not lat or not lon or not linea:
            continue
        if not any(x["linea"] == linea and distancia_km(lat, lon, x["lat"], x["lon"]) < 0.11 for x in lote_limpio):
            lote_limpio.append({**d, "lat": lat, "lon": lon, "linea": linea})

    # Llevar registro de qué buses existentes ya fueron reclamados en este lote (Asignación 1 a 1)
    buses_reclamados = set()

    for d in lote_limpio:
        lat, lon, linea = d["lat"], d["lon"], d["linea"]
        min_eta = int(d.get("_min_eta") or extraer_minutos(d.get("tiempo") or d.get("tiempo_arribo")))
        sentido_bandera, code_bandera = deducir_sentido_bandera(d.get("ramal"))
        sentido_geo, code_geo, d_nqn, d_plo = deducir_sentido_geometria(linea, lat, lon)

        bus_match_id = None
        menor_score = 999.0

        # CAPA 2: Emparejamiento 1 a 1 comparando contra posición real y posición proyectada
        for b_id, b in ESTADO_GLOBAL["buses"].items():
            if b["linea"] != linea or b_id in buses_reclamados:
                continue

            dist_directa = distancia_km(b["lat"], b["lon"], lat, lon)
            lat_proy, lon_proy = estimar_posicion_proyectada(b, ahora)
            dist_proy = distancia_km(lat_proy, lon_proy, lat, lon)
            dist_efectiva = min(dist_directa, dist_proy)

            edad_bus = ahora - b["last_gps_at"]
            radio_max = 2.2 if edad_bus > 25 else 1.4

            if dist_efectiva < radio_max:
                penalizacion = 0.25 if (code_bandera and code_bandera != b["sentido_code"]) else 0.0
                score = dist_efectiva + penalizacion
                if score < menor_score:
                    menor_score = score
                    bus_match_id = b_id

        if bus_match_id:
            buses_reclamados.add(bus_match_id)
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            dist_avance = distancia_km(bus["lat"], bus["lon"], lat, lon)
            delta_lon = lon - bus["lon"]
            dt = max(ahora - bus["last_gps_at"], 1.0)

            if abs(d_nqn - d_plo) > 0.08:
                sentido, sentido_code = sentido_geo, code_geo
            elif abs(delta_lon) > 0.00035:
                sentido = "Hacia Plottier" if delta_lon < 0 else "Hacia Neuquén"
                sentido_code = "HACIA_PLOTTIER" if delta_lon < 0 else "HACIA_NEUQUEN"
            elif sentido_bandera:
                eta_previa = bus.get("min_eta_radar", 999)
                edad_eta_previa = ahora - bus.get("eta_radar_at", 0)
                if code_bandera != bus["sentido_code"] and edad_eta_previa < 45 and min_eta > eta_previa + 4:
                    sentido, sentido_code = bus["sentido"], bus["sentido_code"]
                else:
                    sentido, sentido_code = sentido_bandera, code_bandera
                    bus["min_eta_radar"] = min_eta
                    bus["eta_radar_at"] = ahora
            else:
                sentido, sentido_code = bus["sentido"], bus["sentido_code"]

            if min_eta <= bus.get("min_eta_radar", 999) or (ahora - bus.get("eta_radar_at", 0)) >= 45:
                bus["min_eta_radar"] = min_eta
                bus["eta_radar_at"] = ahora

            if dist_avance > 0.010:
                vel_kmh = round(max(18.0, min((dist_avance / dt) * 3600.0, 45.0)), 1)
                bus.update({
                    "prev_lat": bus["lat"],
                    "prev_lon": bus["lon"],
                    "lat": lat,
                    "lon": lon,
                    "vel_kmh": vel_kmh,
                    "last_gps_at": ahora,
                    "intentos_rescate": 0
                })
            elif ahora - bus["last_gps_at"] < 150:
                bus["last_gps_at"] = max(bus["last_gps_at"], ahora - 12)
                bus["intentos_rescate"] = 0

            ramal_actual = str(d.get("ramal") or bus.get("ramal") or f"Línea {linea}")
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("VUELTA", "IDA")

            bus.update({
                "ramal": ramal_actual,
                "sentido": sentido,
                "sentido_code": sentido_code,
                "cabecera": detectar_cabecera(lat, lon),
                "updated_at": ahora
            })
        else:
            nuevo_id = f"{linea}_{ESTADO_GLOBAL['contador_ids']}"
            ESTADO_GLOBAL["contador_ids"] += 1
            if abs(d_nqn - d_plo) > 0.06:
                sentido, sentido_code = sentido_geo, code_geo
            elif sentido_bandera:
                sentido, sentido_code = sentido_bandera, code_bandera
            else:
                sentido, sentido_code = sentido_geo or "Hacia Plottier", code_geo or "HACIA_PLOTTIER"

            ramal_inicial = str(d.get("ramal") or f"Línea {linea}")
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in ramal_inicial.upper():
                ramal_inicial = ramal_inicial.replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in ramal_inicial.upper():
                ramal_inicial = ramal_inicial.replace("VUELTA", "IDA")

            ESTADO_GLOBAL["buses"][nuevo_id] = {
                "id": nuevo_id, "linea": linea, "ramal": ramal_inicial,
                "sentido": sentido, "sentido_code": sentido_code, "lat": lat, "lon": lon,
                "prev_lat": lat, "prev_lon": lon, "vel_kmh": 28.0,
                "min_eta_radar": min_eta, "eta_radar_at": ahora,
                "intentos_rescate": 0, "ultimo_rescate_at": 0.0,
                "cabecera": detectar_cabecera(lat, lon), "last_gps_at": ahora, "updated_at": ahora
            }
            buses_reclamados.add(nuevo_id)

    # Limpiar unidades inactivas (> 8 min) y fusionar cualquier solapamiento
    ESTADO_GLOBAL["buses"] = {k: v for k, v in ESTADO_GLOBAL["buses"].items() if ahora - v["last_gps_at"] < 480}
    fusionar_buses_solapados()

def rescatar_unidades_sin_senal():
    """
    Si algún colectivo lleva más de 20s sin actualizar señal (o falta una línea entera),
    envía una única orden en lote a /rescate del Worker para que consulte a Indalo
    específicamente por esas unidades faltantes.
    """
    ahora = time.time()
    pedidos_rescate = []
    vistas = set()

    # 1. Buscar colectivos activos que estén perdiendo señal (> 20s sin GPS nuevo)
    buses_sin_senal = [
        b for b in ESTADO_GLOBAL["buses"].values()
        if (ahora - b["last_gps_at"]) >= 20 and not (b.get("cabecera") and (ahora - b["last_gps_at"]) > 60)
    ]
    buses_sin_senal.sort(key=lambda x: ahora - x["last_gps_at"], reverse=True)

    for bus in buses_sin_senal[:4]:
        p_rescate = buscar_parada_rescate(bus, ahora)
        bus["intentos_rescate"] = int(bus.get("intentos_rescate", 0)) + 1
        if p_rescate:
            item_str = f"{p_rescate['id']}:{p_rescate['cod']}:{p_rescate['linea']}"
            if item_str not in vistas:
                vistas.add(item_str)
                pedidos_rescate.append(item_str)

    # 2. Si alguna línea principal quedó vacía en el mapa, incluir su parada troncal en el rescate
    lineas_activas = {b["linea"] for b in ESTADO_GLOBAL["buses"].values() if (ahora - b["last_gps_at"]) <= 240}
    for p_id, p_cod, p_lin in MOD_PARADAS.PARADAS_RADAR:
        if p_lin not in lineas_activas and len(pedidos_rescate) < 5:
            item_str = f"{p_id}:{p_cod}:{p_lin}"
            if item_str not in vistas:
                vistas.add(item_str)
                pedidos_rescate.append(item_str)

    if not pedidos_rescate:
        return

    try:
        rp = requests.get(
            f"{URL_WORKER}rescate",
            params={"items": ",".join(pedidos_rescate)},
            timeout=8
        )
        if rp.status_code == 200:
            buses_recuperados = rp.json().get("buses", [])
            if buses_recuperados:
                procesar_nuevas_posiciones(buses_recuperados)
    except Exception:
        pass

def ejecutar_paso_radar(cantidad_paradas=5):
    if not RADAR_LOCK.acquire(blocking=False):
        return
    try:
        ESTADO_GLOBAL["ultimo_escaneo"] = time.time()

        # 1. Pedir al Worker el barrido general de la flota (responde en ~1.5s con las paradas nuevas)
        try:
            r = requests.get(URL_WORKER, timeout=9)
            if r.status_code == 200:
                procesar_nuevas_posiciones(r.json().get("buses", []))
        except Exception:
            pass

        # 2. Si algún colectivo sigue sin reportar señal, enviar señal dirigida a /rescate del Worker
        rescatar_unidades_sin_senal()

        try:
            ESTADO_GLOBAL["timestamp"] = datetime.now(zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")
    finally:
        RADAR_LOCK.release()

def recolector_fondo():
    while True:
        ejecutar_paso_radar(5)
        time.sleep(7)

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

def encontrar_indice_parada_adelante(coords_parada, traza, idx_bus):
    mejor_idx_stop, menor_d_stop = -1, 999.0
    for (plat, plon) in coords_parada:
        umbral_km = 0.22 if plon > -68.088 else 0.065
        for i in range(max(0, idx_bus - 2), len(traza)):
            pt = traza[i]
            d = distancia_km(plat, plon, pt[0], pt[1])
            if d <= umbral_km and d < menor_d_stop:
                menor_d_stop = d
                mejor_idx_stop = i
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

        # Usar la posición proyectada si el colectivo lleva unos segundos sin señal
        lat_actual, lon_actual = estimar_posicion_proyectada(bus, ahora)
        idx_bus, dist_bus_traza = indice_mas_cercano(lat_actual, lon_actual, traza)
        limite_desvio_bus = 0.65 if lon_actual > -68.088 else 0.25
        if dist_bus_traza > limite_desvio_bus:
            continue

        idx_stop, _ = encontrar_indice_parada_adelante(coords_parada, traza, idx_bus)
        if idx_stop == -1:
            continue

        dist_recorrido_km = max(0.0, traza[idx_stop][2] - traza[idx_bus][2])
        if dist_recorrido_km > 22.0:
            continue

        tiempo_txt, min_orden = formatear_rango_arribo(dist_recorrido_km, lon_actual)
        arribos_calculados.append({
            "ramal": bus["ramal"],
            "sentido": bus["sentido"],
            "tiempo": tiempo_txt,
            "lat": lat_actual,
            "lon": lon_actual,
            "_min": min_orden
        })

    arribos_calculados.sort(key=lambda x: x["_min"])
    return jsonify({"arribos": arribos_calculados[:4]})

@app.route('/api/radar')
def api_radar():
    ahora = time.time()
    lista = [{**b, "edad_senal": int(max(0, ahora - b["last_gps_at"]))} for b in ESTADO_GLOBAL["buses"].values()]
    return jsonify({"timestamp": ESTADO_GLOBAL["timestamp"], "buses": lista, "total_buses": len(lista)})

@app.route('/api/static_data')
def api_static_data():
    return jsonify({
        "trazas": TRAZAS_GEO,
        "paradas": PARADAS_CLUSTERIZADAS,
        "paradas_raw": PARADAS_RAW,
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
