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

def densificar_traza(puntos, paso_km=0.025):
    """Subdivide la polilínea cada 25 metros para calcular distancias exactas en memoria."""
    if not puntos or len(puntos) < 2:
        return puntos or []
    res = [puntos[0]]
    for i in range(len(puntos) - 1):
        p1, p2 = puntos[i], puntos[i + 1]
        d = distancia_km(p1[0], p1[1], p2[0], p2[1])
        pasos = max(1, int(math.ceil(d / paso_km)))
        for s in range(1, pasos + 1):
            t = s / pasos
            res.append([
                round(p1[0] + (p2[0] - p1[0]) * t, 6),
                round(p1[1] + (p2[1] - p1[1]) * t, 6)
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
    TRAZAS_DENSAS[lin][sentido] = densificar_traza(pts)

# Diccionario rápido de coordenadas por ID de parada para cálculos en memoria
MAPA_COORDS_PARADAS = {str(p[0]).strip(): (float(p[1]), float(p[2])) for p in PARADAS_RAW}

# Procesar y agrupar paradas usando el módulo externo
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

def filtrar_arribos_unicos(arribos, linea):
    ordenados = sorted(arribos, key=lambda a: extraer_minutos(a.get("tiempo") or a.get("tiempo_arribo")))
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

def indice_mas_cercano(lat, lon, traza):
    mejor_idx, menor_d = 0, 999.0
    for i, pt in enumerate(traza):
        d = distancia_km(lat, lon, pt[0], pt[1])
        if d < menor_d:
            menor_d = d
            mejor_idx = i
    return mejor_idx, menor_d

def procesar_nuevas_posiciones(detecciones):
    ahora = time.time()
    for d in detecciones:
        try:
            lat, lon = float(d.get("lat") or 0), float(d.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        linea = normalizar_linea(d.get("linea"))
        if not lat or not lon or not linea:
            continue

        sentido_bandera, code_bandera = deducir_sentido_bandera(d.get("ramal"))
        sentido_geo, code_geo, d_nqn, d_plo = deducir_sentido_geometria(linea, lat, lon)

        bus_match_id, min_dist = None, 1.8
        for b_id, b in ESTADO_GLOBAL["buses"].items():
            if b["linea"] == linea:
                dist = distancia_km(b["lat"], b["lon"], lat, lon)
                if dist < min_dist:
                    min_dist, bus_match_id = dist, b_id

        if bus_match_id:
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            dist_avance = distancia_km(bus["lat"], bus["lon"], lat, lon)
            delta_lon = lon - bus["lon"]
            dt = max(ahora - bus["last_gps_at"], 1.0)

            if abs(d_nqn - d_plo) > 0.08:
                sentido, sentido_code = sentido_geo, code_geo
            elif abs(delta_lon) > 0.0003:
                sentido = "Hacia Plottier" if delta_lon < 0 else "Hacia Neuquén"
                sentido_code = "HACIA_PLOTTIER" if delta_lon < 0 else "HACIA_NEUQUEN"
            elif sentido_bandera:
                sentido, sentido_code = sentido_bandera, code_bandera
            else:
                sentido, sentido_code = bus["sentido"], bus["sentido_code"]

            if dist_avance > 0.012:
                vel_kmh = round(max(18.0, min((dist_avance / dt) * 3600.0, 58.0)), 1)
                bus.update({"prev_lat": bus["lat"], "prev_lon": bus["lon"], "lat": lat, "lon": lon, "vel_kmh": vel_kmh, "last_gps_at": ahora})
            elif ahora - bus["last_gps_at"] < 120:
                bus["last_gps_at"] = max(bus["last_gps_at"], ahora - 25)

            ramal_actual = str(d.get("ramal") or bus.get("ramal") or f"Línea {linea}")
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in ramal_actual.upper():
                ramal_actual = ramal_actual.replace("VUELTA", "IDA")

            bus.update({"ramal": ramal_actual, "sentido": sentido, "sentido_code": sentido_code, "cabecera": detectar_cabecera(lat, lon), "updated_at": ahora})
        else:
            nuevo_id = f"{linea}_{ESTADO_GLOBAL['contador_ids']}"
            ESTADO_GLOBAL["contador_ids"] += 1
            if abs(d_nqn - d_plo) > 0.06:
                sentido, sentido_code = sentido_geo, code_geo
            elif sentido_bandera:
                sentido, sentido_code = sentido_bandera, code_bandera
            else:
                sentido, sentido_code = sentido_geo or "Hacia Plottier", code_geo or "HACIA_PLOTTIER"

            ESTADO_GLOBAL["buses"][nuevo_id] = {
                "id": nuevo_id, "linea": linea, "ramal": d.get("ramal") or f"Línea {linea}",
                "sentido": sentido, "sentido_code": sentido_code, "lat": lat, "lon": lon,
                "prev_lat": lat, "prev_lon": lon, "vel_kmh": 34.0,
                "cabecera": detectar_cabecera(lat, lon), "last_gps_at": ahora, "updated_at": ahora
            }

    ESTADO_GLOBAL["buses"] = {k: v for k, v in ESTADO_GLOBAL["buses"].items() if ahora - v["last_gps_at"] < 480}

def ejecutar_paso_radar(cantidad_paradas=5):
    if not RADAR_LOCK.acquire(blocking=False):
        return
    try:
        ESTADO_GLOBAL["ultimo_escaneo"] = time.time()
        try:
            r = requests.get(URL_WORKER, timeout=8)
            if r.status_code == 200:
                procesar_nuevas_posiciones(r.json().get("buses", []))
        except Exception:
            pass

        paradas_radar = MOD_PARADAS.PARADAS_RADAR
        idx = ESTADO_GLOBAL["idx_radar"]
        lote = [paradas_radar[(idx + i) % len(paradas_radar)] for i in range(cantidad_paradas)]
        ESTADO_GLOBAL["idx_radar"] = (idx + cantidad_paradas) % len(paradas_radar)

        for p_id, p_cod, p_lin in lote:
            try:
                rp = requests.get(f"{URL_WORKER}parada", params={"id": p_id, "cod": p_cod, "linea": p_lin}, timeout=6)
                if rp.status_code == 200:
                    procesar_nuevas_posiciones(filtrar_arribos_unicos(rp.json().get("arribos", []), p_lin))
            except Exception:
                pass

        try:
            ESTADO_GLOBAL["timestamp"] = datetime.now(zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")
    finally:
        RADAR_LOCK.release()

def recolector_fondo():
    while True:
        ejecutar_paso_radar(5)
        time.sleep(9)

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
    """
    SOLUCIÓN 1 ACTIVA (Cero consultas a Indalo al tocar paradas):
    Calcula los arribos instantáneamente en memoria usando las unidades ya rastreadas
    en ESTADO_GLOBAL['buses'] y la geometría densificada del recorrido.
    """
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
        vel_kmh = max(22.0, min(float(bus.get("vel_kmh") or 32.0), 48.0))

        if len(traza) >= 2:
            idx_bus, dist_bus_traza = indice_mas_cercano(bus["lat"], bus["lon"], traza)
            # Buscar cuál de las paradas del grupo corresponde al sentido de este colectivo
            mejor_idx_stop, menor_dist_stop = -1, 999.0
            for (plat, plon) in coords_parada:
                idx_s, dist_s = indice_mas_cercano(plat, plon, traza)
                if dist_s < menor_dist_stop:
                    menor_dist_stop = dist_s
                    mejor_idx_stop = idx_s

            # Verificar que la parada pertenezca a este sentido (< 180m de la traza) y el colectivo no la haya pasado
            if menor_dist_stop <= 0.18 and mejor_idx_stop >= idx_bus - 1:
                dist_recorrido_km = max(0.0, (mejor_idx_stop - idx_bus) * 0.025)
                if dist_recorrido_km <= 0.07:
                    tiempo_txt = "Llegando"
                    min_orden = 0
                else:
                    min_orden = max(1, int(round((dist_recorrido_km / vel_kmh) * 60)))
                    tiempo_txt = f"{min_orden} min. aprox."

                arribos_calculados.append({
                    "ramal": bus["ramal"],
                    "sentido": bus["sentido"],
                    "tiempo": tiempo_txt,
                    "lat": bus["lat"],
                    "lon": bus["lon"],
                    "_min": min_orden
                })
                continue

        # Respaldo geométrico si el colectivo va por un desvío fuera de la traza habitual
        plat, plon = coords_parada[0]
        delta_lon = plon - bus["lon"]
        viene_hacia_aca = (sentido_code == "HACIA_NEUQUEN" and delta_lon > -0.001) or \
                          (sentido_code == "HACIA_PLOTTIER" and delta_lon < 0.001)
        if viene_hacia_aca:
            dist_km = distancia_km(bus["lat"], bus["lon"], plat, plon) * 1.25
            if dist_km <= 14.0:
                min_orden = max(1, int(round((dist_km / vel_kmh) * 60)))
                arribos_calculados.append({
                    "ramal": bus["ramal"],
                    "sentido": bus["sentido"],
                    "tiempo": f"{min_orden} min. aprox.",
                    "lat": bus["lat"],
                    "lon": bus["lon"],
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
