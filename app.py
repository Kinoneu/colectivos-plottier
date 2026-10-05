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

for rec in raw_recorridos:
    cod = str(rec.get("codigoLinea"))
    lin = MAPA_LINEAS.get(cod)
    if not lin:
        continue
    sentido = "HACIA_NEUQUEN" if "IDA" in rec.get("bandera", "").upper() else "HACIA_PLOTTIER"
    TRAZAS_GEO[lin][sentido] = [
        [round(float(p["latitud"]), 6), round(float(p["longitud"]), 6)]
        for p in rec.get("puntos", [])
        if p.get("latitud") and p.get("longitud")
    ]

PARADAS_CLUSTERIZADAS = MOD_PARADAS.agrupar_paradas_inteligente(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"
ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {},
    "contador_ids": 1,
    "idx_radar": 0,
    "ultimo_escaneo": 0.0,
    "ultimo_aporte_usuario": 0.0
}
CACHE_PARADAS = {}
RADAR_LOCK = Lock()

def actualizar_reloj():
    try:
        ESTADO_GLOBAL["timestamp"] = datetime.now(zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
    except Exception:
        ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")

def distancia_km(lat1, lon1, lat2, lon2):
    return math.sqrt(((lat1 - lat2) * 111.0) ** 2 + ((lon1 - lon2) * 111.0 * 0.777) ** 2)

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
    pts_nqn = TRAZAS_GEO.get(linea, {}).get("HACIA_NEUQUEN", [])
    pts_plo = TRAZAS_GEO.get(linea, {}).get("HACIA_PLOTTIER", [])
    d_nqn = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_nqn], default=99)
    d_plo = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_plo], default=99)
    if d_plo < d_nqn:
        return "Hacia Plottier", "HACIA_PLOTTIER", d_nqn, d_plo
    return "Hacia Neuquén", "HACIA_NEUQUEN", d_nqn, d_plo

def procesar_nuevas_posiciones(detecciones):
    ahora = time.time()
    for d in detecciones:
        try:
            lat, lon = float(d.get("lat") or 0), float(d.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        # Filtro geográfico básico para ignorar coordenadas inválidas fuera del Alto Valle
        if not (-39.20 <= lat <= -38.75 and -68.55 <= lon <= -67.90):
            continue
        linea = normalizar_linea(d.get("linea"))
        if not linea:
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
    actualizar_reloj()

def ejecutar_paso_radar(cantidad_paradas=3):
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
    finally:
        RADAR_LOCK.release()

def recolector_fondo():
    while True:
        # Si hay usuarios activos aportando datos desde sus dispositivos, Render reduce sus propias consultas para no saturar
        usuarios_aportando = (time.time() - ESTADO_GLOBAL.get("ultimo_aporte_usuario", 0)) < 35
        ejecutar_paso_radar(2 if usuarios_aportando else 4)
        time.sleep(14 if usuarios_aportando else 10)

Thread(target=recolector_fondo, daemon=True).start()

@app.route('/api/aportar', methods=['POST'])
def api_aportar():
    """
    Recibe los arribos que consultaron directamente los dispositivos de los usuarios
    y los integra al mapa global para todos los demás vecinos.
    """
    data = request.get_json(silent=True) or {}
    linea = data.get("linea", "")
    parada_key = data.get("parada_key", "")
    arribos = data.get("arribos", [])

    if not isinstance(arribos, list) or not linea:
        return jsonify({"ok": False})

    for a in arribos:
        sent_real, _ = deducir_sentido_bandera(a.get("ramal"))
        if sent_real:
            a["sentido"] = sent_real

    if arribos:
        ESTADO_GLOBAL["ultimo_aporte_usuario"] = time.time()
        procesar_nuevas_posiciones(filtrar_arribos_unicos(arribos, linea))
        if parada_key:
            CACHE_PARADAS[parada_key] = (time.time(), arribos)

    return jsonify({"ok": True, "total_buses": len(ESTADO_GLOBAL["buses"])})

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
    p_cod = request.args.get("cod", "")
    p_linea = request.args.get("linea", "")
    if not p_id_raw or not p_cod:
        return jsonify({"arribos": []})

    ahora = time.time()
    clave_cache = f"{p_id_raw}_{p_cod}_{p_linea}"
    # Si otro vecino consultó esta misma parada hace menos de 20 segundos, comparte el resultado al instante
    if clave_cache in CACHE_PARADAS and ahora - CACHE_PARADAS[clave_cache][0] < 20:
        return jsonify({"arribos": CACHE_PARADAS[clave_cache][1]})

    ids_consulta = [x.strip() for x in p_id_raw.split(",") if x.strip()][:3]
    arribos_totales = []

    for pid in ids_consulta:
        try:
            r = requests.get(f"{URL_WORKER}parada", params={"id": pid, "cod": p_cod, "linea": p_linea}, timeout=7)
            if r.status_code == 200:
                for a in r.json().get("arribos", []):
                    sent_real, _ = deducir_sentido_bandera(a.get("ramal"))
                    if sent_real:
                        a["sentido"] = sent_real
                    arribos_totales.append(a)
        except Exception:
            pass

    if arribos_totales:
        procesar_nuevas_posiciones(filtrar_arribos_unicos(arribos_totales, p_linea))
        CACHE_PARADAS[clave_cache] = (ahora, arribos_totales)
        return jsonify({"arribos": arribos_totales})

    if clave_cache in CACHE_PARADAS and ahora - CACHE_PARADAS[clave_cache][0] < 75:
        return jsonify({"arribos": CACHE_PARADAS[clave_cache][1]})
    return jsonify({"arribos": []})

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
