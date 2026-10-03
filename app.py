import os
import re
import time
import json
import math
import requests
from datetime import datetime
import zoneinfo
from threading import Thread, Lock
from flask import Flask, jsonify, render_template_string, request, send_file, Response

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Cargar paradas y trazas con rutas seguras
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
    # Con las nuevas cabeceras en Plottier, IDA va hacia Neuquén y VUELTA hacia Plottier
    sentido = "HACIA_NEUQUEN" if "IDA" in rec.get("bandera", "").upper() else "HACIA_PLOTTIER"
    TRAZAS_GEO[lin][sentido] = [
        [round(float(p["latitud"]), 6), round(float(p["longitud"]), 6)]
        for p in rec.get("puntos", [])
        if p.get("latitud") and p.get("longitud")
    ]

# Cabeceras conocidas donde los colectivos apagan el GPS al terminar el recorrido
CABECERAS_GEO = [
    (-38.9314, -68.2494, "Cabecera Plottier Norte"),
    (-38.9345, -68.2585, "Cabecera Casa de Té"),
    (-38.9302, -68.2585, "Cabecera Aristóbulo del Valle"),
    (-38.9607, -68.2491, "Cabecera Plottier Sur"),
    (-38.9645, -68.2433, "Cabecera Zabaleta"),
    (-38.9562, -68.2176, "Terminal ETOP Plottier"),
    (-38.9561, -68.3385, "Cabecera Las Lilas / 50R"),
    (-38.9840, -68.3494, "Cabecera B° Las Perlas"),
    (-38.9822, -68.3070, "Cabecera Las Perlas Este"),
    (-38.9461, -68.0575, "Cabecera Neuquén Centro"),
    (-38.9571, -68.0562, "Cabecera Neuquén Parque Central")
]

# 2. Agrupar paradas cercanas conservando TODOS los IDs de parada de esa esquina por línea
def agrupar_paradas(paradas, radio_mts=35):
    grupos = []
    for p in paradas:
        id_p, lat, lon, desc, lineas = p
        unido = False
        for g in grupos:
            d_lat = (lat - g["lat"]) * 111139
            d_lon = (lon - g["lon"]) * 111139 * 0.777
            if math.sqrt(d_lat**2 + d_lon**2) <= radio_mts:
                for lin_nom, lin_cod in lineas.items():
                    if lin_nom not in g["lineas"]:
                        g["lineas"][lin_nom] = {"cod": lin_cod, "parada": id_p, "ids": [id_p]}
                    else:
                        if id_p not in g["lineas"][lin_nom]["ids"]:
                            if id_p.upper().startswith("NV") or id_p.upper().startswith("N"):
                                g["lineas"][lin_nom]["ids"].insert(0, id_p)
                            else:
                                g["lineas"][lin_nom]["ids"].append(id_p)
                            g["lineas"][lin_nom]["parada"] = ",".join(g["lineas"][lin_nom]["ids"][:2])
                if id_p not in g["ids"]:
                    g["ids"].append(id_p)
                unido = True
                break
        if not unido:
            grupos.append({
                "ids": [id_p],
                "lat": lat,
                "lon": lon,
                "desc": desc,
                "lineas": {
                    lin_nom: {"cod": lin_cod, "parada": id_p, "ids": [id_p]}
                    for lin_nom, lin_cod in lineas.items()
                }
            })
    return [
        [" / ".join(g["ids"][:2]), g["lat"], g["lon"], g["desc"], g["lineas"]]
        for g in grupos
    ]

PARADAS_CLUSTERIZADAS = agrupar_paradas(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"

PARADAS_RADAR = [
    ("NV4120", "1013", "50A"),
    ("NV1012", "1013", "50A"),
    ("NV8039", "1013", "50A"),
    ("NV1027", "1013", "50A"),
    ("NV4120", "1014", "50B"),
    ("NV1012", "1014", "50B"),
    ("NV1173", "1014", "50B"),
    ("NV1027", "1014", "50B"),
    ("NV 4998", "1015", "50R"),
    ("NV6001", "1015", "50R"),
    ("NV5019", "1015", "50R"),
    ("NV8064", "1109", "URBANO"),
    ("51 00001", "1109", "URBANO"),
    ("5200001", "1079", "52 CENTRO"),
    ("5200047", "1079", "52 CENTRO"),
    ("5200001", "1080", "52 UNION"),
    ("5200047", "1080", "52 UNION")
]

ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {},
    "contador_ids": 1,
    "idx_radar": 0,
    "ultimo_escaneo": 0.0
}
CACHE_PARADAS = {}
RADAR_LOCK = Lock()

def distancia_km(lat1, lon1, lat2, lon2):
    d_lat = (lat1 - lat2) * 111.0
    d_lon = (lon1 - lon2) * 111.0 * 0.777
    return math.sqrt(d_lat**2 + d_lon**2)

def detectar_cabecera(lat, lon):
    for c_lat, c_lon, c_nom in CABECERAS_GEO:
        if distancia_km(lat, lon, c_lat, c_lon) <= 0.35:
            return c_nom
    return None

def normalizar_linea(linea_raw):
    lin = str(linea_raw or "").upper().strip()
    if "51" in lin or "URBANO" in lin:
        return "URBANO"
    if "50A" in lin or "50 A" in lin:
        return "50A"
    if "50B" in lin or "50 B" in lin:
        return "50B"
    if "50R" in lin or "50 R" in lin:
        return "50R"
    if "UNION" in lin:
        return "52 UNION"
    if "52" in lin:
        return "52 CENTRO"
    return lin

def extraer_minutos(tiempo_str):
    m = re.search(r'(\d+)', str(tiempo_str or ""))
    return int(m.group(1)) if m else 999

def filtrar_arribos_unicos(arribos, linea):
    ordenados = sorted(arribos, key=lambda a: extraer_minutos(a.get("tiempo") or a.get("tiempo_arribo")))
    unicos = []
    for a in ordenados:
        try:
            lat = float(a.get("lat") or 0)
            lon = float(a.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        if not lat or not lon:
            continue
        duplicado = False
        for u in unicos:
            if distancia_km(lat, lon, float(u["lat"]), float(u["lon"])) < 0.05:
                duplicado = True
                break
        if not duplicado:
            unicos.append({**a, "linea": linea})
    return unicos

def deducir_sentido_bandera(ramal_raw):
    txt = str(ramal_raw or "").upper()
    if "VUELTA" in txt or "VTA" in txt:
        return "Hacia Plottier", "HACIA_PLOTTIER"
    if "IDA" in txt:
        return "Hacia Neuquén", "HACIA_NEUQUEN"
    return None, None

def deducir_sentido_geometria(linea, lat, lon):
    if linea not in TRAZAS_GEO:
        return None, None, 99, 99
    pts_nqn = TRAZAS_GEO[linea].get("HACIA_NEUQUEN", [])
    pts_plo = TRAZAS_GEO[linea].get("HACIA_PLOTTIER", [])
    d_nqn = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_nqn], default=99)
    d_plo = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_plo], default=99)
    if d_plo < d_nqn:
        return "Hacia Plottier", "HACIA_PLOTTIER", d_nqn, d_plo
    return "Hacia Neuquén", "HACIA_NEUQUEN", d_nqn, d_plo

def procesar_nuevas_posiciones(detecciones):
    global ESTADO_GLOBAL
    ahora = time.time()

    for d in detecciones:
        try:
            lat = float(d.get("lat") or 0)
            lon = float(d.get("lon") or 0)
        except (ValueError, TypeError):
            continue
        linea = normalizar_linea(d.get("linea"))
        if not lat or not lon or not linea:
            continue

        sentido_bandera, code_bandera = deducir_sentido_bandera(d.get("ramal"))
        sentido_geo, code_geo, d_nqn, d_plo = deducir_sentido_geometria(linea, lat, lon)

        bus_match_id = None
        min_dist = 1.8
        for b_id, b in ESTADO_GLOBAL["buses"].items():
            if b["linea"] == linea:
                dist = distancia_km(b["lat"], b["lon"], lat, lon)
                if dist < min_dist:
                    min_dist = dist
                    bus_match_id = b_id

        if bus_match_id:
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            dist_avance = distancia_km(bus["lat"], bus["lon"], lat, lon)
            delta_lon = lon - bus["lon"]
            dt = max(ahora - bus["last_gps_at"], 1.0)

            if abs(d_nqn - d_plo) > 0.08:
                sentido = sentido_geo
                sentido_code = code_geo
            elif abs(delta_lon) > 0.0003:
                if delta_lon < 0:
                    sentido = "Hacia Plottier"
                    sentido_code = "HACIA_PLOTTIER"
                else:
                    sentido = "Hacia Neuquén"
                    sentido_code = "HACIA_NEUQUEN"
            elif sentido_bandera:
                sentido = sentido_bandera
                sentido_code = code_bandera
            else:
                sentido = bus["sentido"]
                sentido_code = bus["sentido_code"]

            if dist_avance > 0.012:
                vel_calc = (dist_avance / dt) * 3600.0
                vel_kmh = round(max(18.0, min(vel_calc, 58.0)), 1)
                bus.update({
                    "prev_lat": bus["lat"],
                    "prev_lon": bus["lon"],
                    "lat": lat,
                    "lon": lon,
                    "vel_kmh": vel_kmh,
                    "last_gps_at": ahora
                })
            else:
                if ahora - bus["last_gps_at"] < 120:
                    bus["last_gps_at"] = max(bus["last_gps_at"], ahora - 25)

            ramal_actual = d.get("ramal") or bus.get("ramal") or f"Línea {linea}"
            if sentido_code == "HACIA_PLOTTIER" and "IDA" in str(ramal_actual).upper():
                ramal_actual = str(ramal_actual).replace("IDA", "VUELTA")
            elif sentido_code == "HACIA_NEUQUEN" and "VUELTA" in str(ramal_actual).upper():
                ramal_actual = str(ramal_actual).replace("VUELTA", "IDA")

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
                sentido = sentido_geo
                sentido_code = code_geo
            elif sentido_bandera:
                sentido = sentido_bandera
                sentido_code = code_bandera
            else:
                sentido = sentido_geo or "Hacia Plottier"
                sentido_code = code_geo or "HACIA_PLOTTIER"

            ESTADO_GLOBAL["buses"][nuevo_id] = {
                "id": nuevo_id,
                "linea": linea,
                "ramal": d.get("ramal") or f"Línea {linea}",
                "sentido": sentido,
                "sentido_code": sentido_code,
                "lat": lat,
                "lon": lon,
                "prev_lat": lat,
                "prev_lon": lon,
                "vel_kmh": 34.0,
                "cabecera": detectar_cabecera(lat, lon),
                "last_gps_at": ahora,
                "updated_at": ahora
            }

    ESTADO_GLOBAL["buses"] = {
        k: v for k, v in ESTADO_GLOBAL["buses"].items()
        if ahora - v["last_gps_at"] < 480
    }

def ejecutar_paso_radar(cantidad_paradas=5):
    global ESTADO_GLOBAL
    if not RADAR_LOCK.acquire(blocking=False):
        return
    try:
        ESTADO_GLOBAL["ultimo_escaneo"] = time.time()
        try:
            r = requests.get(URL_WORKER, timeout=8)
            if r.status_code == 200:
                data = r.json()
                procesar_nuevas_posiciones(data.get("buses", []))
        except Exception:
            pass

        idx = ESTADO_GLOBAL["idx_radar"]
        lote = [PARADAS_RADAR[(idx + i) % len(PARADAS_RADAR)] for i in range(cantidad_paradas)]
        ESTADO_GLOBAL["idx_radar"] = (idx + cantidad_paradas) % len(PARADAS_RADAR)

        for p_id, p_cod, p_lin in lote:
            try:
                rp = requests.get(
                    f"{URL_WORKER}parada",
                    params={"id": p_id, "cod": p_cod, "linea": p_lin},
                    timeout=6
                )
                if rp.status_code == 200:
                    arribos = rp.json().get("arribos", [])
                    procesar_nuevas_posiciones(filtrar_arribos_unicos(arribos, p_lin))
            except Exception:
                pass

        try:
            tz = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
            ESTADO_GLOBAL["timestamp"] = datetime.now(tz).strftime("%H:%M:%S")
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
    html_minimo = "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body style='background:#fff;color:#000;font-family:sans-serif;margin:8px;'>ok</body></html>"
    return Response(html_minimo, status=200, mimetype='text/html')

@app.route('/logo.png')
@app.route('/favicon.ico')
def logo_sitio():
    """Sirve el logotipo subido a GitHub (logo.png, logo.jpg, etc.) para WhatsApp, Google y pestaña."""
    nombres_logo = [
        "logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.ico",
        "Logo.png", "Logo.jpg", "icono.png", "icono.jpg"
    ]
    for nombre in nombres_logo:
        ruta = os.path.join(BASE_DIR, nombre)
        if os.path.isfile(ruta):
            return send_file(ruta)
    return ("", 404)

@app.route('/foto_perfil')
def foto_perfil():
    """Sirve la foto de perfil subida a GitHub (perfil.jpg, perfil.png, etc.)."""
    nombres_posibles = [
        "perfil.jpg", "perfil.png", "perfil.jpeg", "perfil.webp",
        "Perfil.jpg", "Perfil.png", "foto.jpg", "foto.png"
    ]
    for nombre in nombres_posibles:
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

    if clave_cache in CACHE_PARADAS:
        ts_cache, arribos_cache = CACHE_PARADAS[clave_cache]
        if ahora - ts_cache < 18 and arribos_cache:
            return jsonify({"arribos": arribos_cache})

    ids_consulta = [x.strip() for x in p_id_raw.split(",") if x.strip()][:2]
    arribos_totales = []

    for pid in ids_consulta:
        try:
            r = requests.get(
                f"{URL_WORKER}parada",
                params={"id": pid, "cod": p_cod, "linea": p_linea},
                timeout=7
            )
            if r.status_code == 200:
                data = r.json()
                for a in data.get("arribos", []):
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

    if clave_cache in CACHE_PARADAS:
        ts_cache, arribos_cache = CACHE_PARADAS[clave_cache]
        if ahora - ts_cache < 75 and arribos_cache:
            return jsonify({"arribos": arribos_cache})

    return jsonify({"arribos": []})

@app.route('/api/radar')
def api_radar():
    ahora = time.time()
    lista = []
    for b in ESTADO_GLOBAL["buses"].values():
        edad = int(max(0, ahora - b["last_gps_at"]))
        lista.append({**b, "edad_senal": edad})
    return jsonify({
        "timestamp": ESTADO_GLOBAL["timestamp"],
        "buses": lista,
        "total_buses": len(lista)
    })

@app.route('/api/static_data')
def api_static_data():
    return jsonify({
        "trazas": TRAZAS_GEO,
        "paradas": PARADAS_CLUSTERIZADAS,
        "paradas_raw": PARADAS_RAW
    })

@app.route('/')
def home():
    base_url = request.host_url.rstrip('/')
    if base_url.startswith("http://") and "localhost" not in base_url and "127.0.0.1" not in base_url:
        base_url = base_url.replace("http://", "https://", 1)
    return render_template_string(HTML_COMPLETO, base_url=base_url)

HTML_COMPLETO = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - Colectivos en Vivo</title>

  <!-- Iconos para Google Search, pestaña del navegador y pantalla de inicio en celulares -->
  <link rel="icon" type="image/png" sizes="512x512" href="/logo.png">
  <link rel="icon" type="image/png" sizes="192x192" href="/logo.png">
  <link rel="shortcut icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/logo.png">

  <!-- Meta etiquetas Open Graph para vista previa al compartir en WhatsApp y redes -->
  <meta name="description" content="Ubicación GPS en vivo y horarios oficiales de las líneas 50A, 50B, 50R, 51 Urbano y 52 en Plottier y Neuquén.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Transporte Plottier">
  <meta property="og:title" content="Transporte Plottier - Colectivos en Vivo">
  <meta property="og:description" content="Seguimiento GPS en tiempo real y planillas de horarios oficiales (50A, 50B, 50R, 51 Urbano y 52).">
  <meta property="og:url" content="{{ base_url }}/">
  <meta property="og:image" content="{{ base_url }}/logo.png">
  <meta property="og:image:width" content="512">
  <meta property="og:image:height" content="512">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="Transporte Plottier - Colectivos en Vivo">
  <meta name="twitter:description" content="GPS en vivo y planillas oficiales de colectivos en Plottier y Neuquén.">
  <meta name="twitter:image" content="{{ base_url }}/logo.png">

  <!-- Google tag (gtag.js) - Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-CE85R9NET5"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-CE85R9NET5');
  </script>

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 98px; max-width: 980px; margin: 0 auto; }
    header { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
    .brand-wrap { display: flex; align-items: center; gap: 10px; }
    .brand-logo { width: 38px; height: 38px; border-radius: 9px; object-fit: cover; border: 1px solid #313244; flex-shrink: 0; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    .badge-beta { background: rgba(249, 226, 175, 0.12); color: #F9E2AF; border: 1px solid rgba(249, 226, 175, 0.4); font-size: 10px; font-weight: 800; padding: 4px 8px; border-radius: 6px; letter-spacing: 0.4px; text-transform: uppercase; }

    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; box-shadow: 0 4px 20px rgba(0,0,0,0.35); }
    #map { height: 460px; width: 100%; background: #11111B; }
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.92); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #CDD6F4; border: 1px solid #313244; font-weight: 700; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.92); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 10px; cursor: pointer; }
    .status-text { font-size: 12px; color: #A6ADC8; }

    .bus-marker { display: flex; align-items: center; justify-content: center; gap: 4px; padding: 3px 7px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 2px 6px rgba(0,0,0,0.65); position: relative; }
    .bus-marker-50a { background: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background: #38243E; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background: #3E3724; border: 2px solid #F9E2AF; color: #F9E2AF; }
    .bus-marker-52 { background: #3E2824; border: 2px solid #FAB387; color: #FAB387; }

    .bus-weak { border-style: dashed !important; border-color: #F9E2AF !important; animation: pulseWeak 1.6s infinite; }
    .bus-stalled { background: #3B1D26 !important; border-color: #F38BA8 !important; color: #F38BA8 !important; opacity: 0.88; }
    .bus-cabecera { opacity: 0.72; border-style: dotted !important; }

    @keyframes pulseWeak {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }

    /* Ícono resaltado con tilde para las paradas verificadas de las planillas */
    .stop-featured-pin {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #1E3A24;
      border: 2px solid #A6E3A1;
      color: #A6E3A1;
      font-size: 12px;
      font-weight: 900;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 6px rgba(0,0,0,0.75);
      cursor: pointer;
    }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; }
    .stop-popup-badge { display: inline-block; background: #e8f8f5; color: #117a65; border: 1px solid #a3e4d7; font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 4px; margin-bottom: 4px; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 6px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px; }
    .btn-jump-sched { display: inline-block; margin-top: 5px; background: #25335A; color: #89B4FA; border: 1px solid #89B4FA; padding: 3px 8px; border-radius: 5px; font-size: 10.5px; font-weight: 800; cursor: pointer; width: 100%; text-align: center; }
    .result-box { margin-top: 6px; padding-top: 4px; border-top: 1px solid #ccc; font-size: 11px; color: #111; }

    /* Sección de Planillas y Horarios Oficiales */
    .sched-card {
      background: #1E1E2E;
      border: 1px solid #313244;
      border-radius: 14px;
      padding: 14px 16px;
      margin-bottom: 14px;
      scroll-margin-top: 16px;
    }
    .sched-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      user-select: none;
    }
    .sched-header-title {
      font-size: 13.5px;
      font-weight: 800;
      color: #89B4FA;
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .sched-header-btn {
      background: #313244;
      color: #CDD6F4;
      border: 1px solid #45475A;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 9px;
      border-radius: 7px;
    }
    .sched-content {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #313244;
      display: none;
    }
    .sched-tabs {
      display: flex;
      gap: 6px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .sched-tab {
      background: #252739;
      color: #A6ADC8;
      border: 1px solid #45475A;
      padding: 5px 11px;
      border-radius: 8px;
      font-size: 11.5px;
      font-weight: 700;
      cursor: pointer;
    }
    .sched-tab.active {
      background: #89B4FA;
      color: #11111B;
      border-color: #89B4FA;
    }
    .sched-legend {
      display: none;
      background: #181825;
      border: 1px solid #313244;
      border-radius: 8px;
      padding: 8px 10px;
      margin-bottom: 10px;
      font-size: 11px;
      color: #CDD6F4;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px;
    }
    .legend-items {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .legend-tag {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 10.5px;
      font-weight: 700;
    }
    .dot-zone { width: 11px; height: 11px; border-radius: 3px; background: rgba(137, 180, 250, 0.35); border: 2px solid #89B4FA; display: inline-block; }
    .dot-next { width: 11px; height: 11px; border-radius: 3px; background: #1E3A24; border: 2px solid #A6E3A1; display: inline-block; }
    .btn-clear-sched {
      background: #313244;
      color: #F38BA8;
      border: 1px solid #45475A;
      font-size: 10.5px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      cursor: pointer;
    }

    .table-responsive {
      max-height: 340px;
      overflow: auto;
      border-radius: 8px;
      border: 1px solid #313244;
      position: relative;
    }
    table.sched-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 11px;
      text-align: center;
      background: #181825;
      color: #CDD6F4;
    }
    table.sched-table th {
      background: #1E1E2E;
      color: #89B4FA;
      padding: 8px 8px;
      font-weight: 800;
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid #313244;
      white-space: nowrap;
    }
    table.sched-table td {
      padding: 6px 7px;
      border-bottom: 1px solid #262738;
      white-space: nowrap;
    }

    /* 1. Casilla/Columna entera de la zona seleccionada resaltada */
    table.sched-table th.col-zone-active {
      background: #22325A !important;
      color: #FFFFFF !important;
      border-top: 2px solid #89B4FA !important;
      border-left: 2px solid #89B4FA !important;
      border-right: 2px solid #89B4FA !important;
      box-shadow: 0 2px 8px rgba(137, 180, 250, 0.35);
    }
    table.sched-table td.col-zone-active {
      background: rgba(137, 180, 250, 0.16) !important;
      color: #FFFFFF !important;
      font-weight: 700;
      border-left: 2px solid #89B4FA !important;
      border-right: 2px solid #89B4FA !important;
    }
    table.sched-table tr:last-child td.col-zone-active {
      border-bottom: 2px solid #89B4FA !important;
    }

    /* 2. Próximos horarios en la parada seleccionada (verde intenso) */
    table.sched-table td.cell-next-arrival {
      background: #1E3A24 !important;
      color: #A6E3A1 !important;
      font-weight: 900 !important;
      box-shadow: inset 0 0 0 2px #A6E3A1 !important;
    }

    /* 3. Horarios correspondientes a las próximas paradas de ese mismo colectivo (dorado/ámbar) */
    table.sched-table td.cell-next-stops {
      background: rgba(249, 226, 175, 0.20) !important;
      color: #F9E2AF !important;
      font-weight: 800 !important;
      border-top: 1px dashed rgba(249, 226, 175, 0.75) !important;
      border-bottom: 1px dashed rgba(249, 226, 175, 0.75) !important;
    }

    /* Sección Posdata / Acerca de la app */
    .about-card {
      background: #1E1E2E;
      border: 1px solid #313244;
      border-radius: 14px;
      padding: 16px;
      color: #BAC2DE;
      font-size: 12.5px;
      line-height: 1.55;
    }
    .about-title {
      font-size: 13px;
      font-weight: 800;
      color: #89B4FA;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .about-text {
      color: #A6ADC8;
      margin-bottom: 10px;
    }
    .beta-notice {
      background: rgba(249, 226, 175, 0.07);
      border-left: 3px solid #F9E2AF;
      padding: 8px 10px;
      border-radius: 4px 8px 8px 4px;
      font-size: 11.5px;
      color: #CBD2EB;
      margin-bottom: 14px;
    }
    .author-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      padding-top: 12px;
      border-top: 1px solid #313244;
    }
    .author-info {
      display: flex;
      align-items: center;
      gap: 11px;
    }
    .author-avatar-wrap {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      overflow: hidden;
      border: 2px solid #89B4FA;
      background: #313244;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .author-avatar {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .author-initials {
      font-size: 14px;
      font-weight: 800;
      color: #89B4FA;
      display: none;
    }
    .author-name {
      font-size: 13.5px;
      font-weight: 800;
      color: #CDD6F4;
    }
    .author-role {
      font-size: 11.5px;
      color: #9399B2;
    }
    .contact-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #313244;
      color: #A6E3A1;
      border: 1px solid #45475A;
      padding: 7px 12px;
      border-radius: 9px;
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
      transition: background 0.15s ease;
    }
    .contact-btn:hover {
      background: #45475A;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand-wrap">
      <img src="/logo.png" alt="Logo" class="brand-logo" onerror="this.style.display='none';">
      <div>
        <h1>Transporte Plottier</h1>
        <p class="sub">GPS en vivo y planillas oficiales (50A, 50B, 50R, 51 Urbano y 52)</p>
      </div>
    </div>
    <span class="badge-beta">Versión Beta</span>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRutas()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
    <div id="map"></div>
  </div>

  <!-- Desplegable de Planillas de Horarios Oficiales -->
  <section class="sched-card" id="sched-section">
    <div class="sched-header" onclick="togglePlanillas()">
      <div class="sched-header-title" id="sched-title-text">📅 Horarios Oficiales Fin de Semana (50A y 50B)</div>
      <button class="sched-header-btn" id="btn-sched-toggle">Ver Planilla ▾</button>
    </div>
    <div class="sched-content" id="sched-panel">
      <div class="sched-tabs">
        <button class="sched-tab active" data-clave="50A_SAB" onclick="mostrarPlanilla('50A_SAB', this)">50A Sábado</button>
        <button class="sched-tab" data-clave="50A_DOM" onclick="mostrarPlanilla('50A_DOM', this)">50A Domingo</button>
        <button class="sched-tab" data-clave="50B_SAB" onclick="mostrarPlanilla('50B_SAB', this)">50B Sábado</button>
        <button class="sched-tab" data-clave="50B_DOM" onclick="mostrarPlanilla('50B_DOM', this)">50B Domingo</button>
      </div>
      <div class="sched-legend" id="sched-legend-box">
        <div class="legend-items">
          <span class="legend-tag"><span class="dot-zone"></span> <span id="legend-zone-name">Zona seleccionada</span></span>
          <span class="legend-tag"><span class="dot-next"></span> Próximos arribos aquí</span>
          <span class="legend-tag"><span style="width:11px;height:11px;border-radius:3px;background:rgba(249,226,175,0.28);border:2px solid #F9E2AF;display:inline-block;"></span> Horarios en próximas paradas</span>
        </div>
        <button class="btn-clear-sched" onclick="limpiarResaltadoPlanilla()">✕ Quitar filtro</button>
      </div>
      <div class="table-responsive" id="sched-table-box"></div>
    </div>
  </section>

  <!-- Posdata / Nota del desarrollador -->
  <section class="about-card">
    <div class="about-title">💡 P.D. · Proyecto libre y comunitario</div>
    <p class="about-text">
      Esta es una aplicación libre y gratuita pensada para los vecinos de <strong>Plottier</strong> y el público en general.
      Surgió originalmente como una herramienta para mi familia ante la falta de una forma práctica de ver los colectivos y sus recorridos en tiempo real, y decidí abrirla a la comunidad. Cada quien es totalmente libre de usarla y compartirla con quien guste.
    </p>
    <div class="beta-notice">
      ⚠️ <strong>Aviso importante:</strong> La aplicación se encuentra en fase <strong>Beta y en constante desarrollo</strong>. Las ubicaciones en movimiento y los tiempos son estimaciones basadas en los reportes del sistema, por lo que pueden existir demoras o errores y los datos deben tomarse de forma orientativa.
    </div>
    <div class="author-row">
      <div class="author-info">
        <div class="author-avatar-wrap">
          <img src="/foto_perfil" alt="Ramiro Alzogaray" class="author-avatar"
               onerror="this.style.display='none'; document.getElementById('avatar-fallback').style.display='block';">
          <span id="avatar-fallback" class="author-initials">RA</span>
        </div>
        <div>
          <div class="author-name">Ramiro Alzogaray</div>
          <div class="author-role">Desarrollador · Plottier, Neuquén</div>
        </div>
      </div>
      <a class="contact-btn" href="https://wa.me/5492994601098" target="_blank" rel="noopener noreferrer" title="Enviar sugerencia o reportar un error">
        💬 Sugerencias / Errores: 299 460-1098
      </a>
    </div>
  </section>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-text" id="status">Sincronizando...</div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map, capaRuta, capaParadas;
    let busesSim = {};
    let RUTAS_GEO = {};
    let RUTAS_DENSAS = {};
    let PARADAS_LISTA = [];
    let mostrandoParadas = true;
    let planillasAbiertas = false;
    let clavePlanillaActual = "50A_SAB";
    let puntoKeyResaltado = null;

    const LIMITE_DEBIL_SEG = 180;      // 3 minutos (180s) para empezar a titilar como "Señal débil"
    const LIMITE_AVERIA_SEG = 240;     // 4 minutos (240s) para detenerse por pérdida de señal
    const DIST_MAX_EN_RUTA_MTS = 35;   // Si se aleja más de 35m de la ruta, 60fps se apaga

    // --- 7 PUNTOS DE CONTROL OFICIALES DE LAS PLANILLAS DE INDALO CON UBICACIÓN CORREGIDA ---
    const PUNTOS_CONTROL_OFICIALES = [
      {
        key: "LOTEO_SOCIAL",
        nombreOficial: "Loteo Social (Cabecera)",
        lat: -38.930393, lon: -68.252000, // Aristóbulo del Valle (NV1244)
        cols50A: [{ idx: 0, label: "Salida hacia Nqn" }],
        cols50B: [{ idx: 0, label: "Salida hacia Nqn" }]
      },
      {
        key: "SAN_MARTIN_TRABAJO",
        nombreOficial: "San Martín y Av. del Trabajo",
        lat: -38.944473, lon: -68.225598, // Av. del Trabajo y Av. San Martín (5200028)
        cols50A: [{ idx: 1, label: "Hacia Neuquén" }],
        cols50B: [{ idx: 6, label: "Regreso a Plottier" }]
      },
      {
        key: "CASA_CULTURA",
        nombreOficial: "Casa de la Cultura",
        lat: -38.950627, lon: -68.225753, // Av. San Martín y Martellota / Alberdi (NV8039 / NV 1301)
        cols50A: [{ idx: 7, label: "Regreso a Plottier" }],
        cols50B: [{ idx: 1, label: "Hacia Neuquén" }]
      },
      {
        key: "AMANCAY_MUTICIAS",
        nombreOficial: "Amancay y Las Muticias",
        lat: -38.964520, lon: -68.243109, // Los Canales sur (NV1038)
        cols50A: [{ idx: 6, label: "Regreso a Plottier" }],
        cols50B: [{ idx: 2, label: "Hacia Neuquén" }]
      },
      {
        key: "RUTA22_RIAVITZ",
        nombreOficial: "Ruta 22 y Riavitz",
        lat: -38.956680, lon: -68.226224, // Riavitz y Buenos Aires Norte / Ruta 22 (NV1066)
        cols50A: [{ idx: 5, label: "Regreso a Plottier" }],
        cols50B: []
      },
      {
        key: "RIO_COLORADO_IDA",
        nombreOficial: "Río Colorado y Ruta 22",
        lat: -38.956568, lon: -68.167666, // Límite Plottier-Neuquén (NV1012 / NV1027)
        cols50A: [{ idx: 2, label: "Hacia Neuquén" }, { idx: 4, label: "Hacia Plottier" }],
        cols50B: [{ idx: 3, label: "Hacia Neuquén" }, { idx: 5, label: "Hacia Plottier" }]
      },
      {
        key: "SAN_JUAN_BSAS",
        nombreOficial: "San Juan y Buenos Aires (Neuquén)",
        lat: -38.944522, lon: -68.057589, // Cabecera Centro Neuquén (NV1102)
        cols50A: [{ idx: 3, label: "Cabecera Neuquén" }],
        cols50B: [{ idx: 4, label: "Cabecera Neuquén" }]
      }
    ];

    // Secuencia ordenada de Paradas Oficiales según línea y sentido para calcular la próxima parada del colectivo
    const ORDEN_PARADAS_OFICIALES = {
      "50A": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "SAN_MARTIN_TRABAJO", "RIO_COLORADO_IDA", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "RIO_COLORADO_IDA", "RUTA22_RIAVITZ", "AMANCAY_MUTICIAS", "CASA_CULTURA", "SAN_MARTIN_TRABAJO", "LOTEO_SOCIAL"]
      },
      "50B": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "SAN_MARTIN_TRABAJO", "CASA_CULTURA", "AMANCAY_MUTICIAS", "RUTA22_RIAVITZ", "RIO_COLORADO_IDA", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "RIO_COLORADO_IDA", "SAN_MARTIN_TRABAJO", "LOTEO_SOCIAL"]
      },
      "DEFAULT": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "CASA_CULTURA", "RUTA22_RIAVITZ", "RIO_COLORADO_IDA", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "RIO_COLORADO_IDA", "RUTA22_RIAVITZ", "CASA_CULTURA", "LOTEO_SOCIAL"]
      }
    };

    // --- BASE DE DATOS EXACTA DE LAS 4 PLANILLAS DE INDALO ---
    function generarFilasPlanilla(especiales, salidasRegulares, deltas, filaFinal) {
      const filas = [...especiales];
      const acum = [];
      let c = 0;
      for (const d of deltas) { c += d; acum.push(c); }
      for (const sal of salidasRegulares) {
        filas.push(acum.map(m => sumarMinutos(sal, m)));
      }
      if (filaFinal) filas.push(filaFinal);
      return filas;
    }

    function sumarMinutos(hhmm, mins) {
      const partes = hhmm.split(':');
      let mTotal = parseInt(partes[0], 10) * 60 + parseInt(partes[1], 10) + mins;
      mTotal = (mTotal % 1440 + 1440) % 1440;
      const h = String(Math.floor(mTotal / 60)).padStart(2, '0');
      const m = String(mTotal % 60).padStart(2, '0');
      return `${h}:${m}`;
    }

    const PLANILLAS_INDALO = {
      "50A_SAB": {
        nombre: "50A Sábado",
        columnas: ["Loteo Social", "San Martín y Trabajo", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "Ruta 22 y Riavitz", "Amancay y Muticias", "Casa Cultura", "Loteo Social"],
        filas: generarFilasPlanilla(
          [
            ["04:25","04:37","04:54","05:40","06:17","06:29","06:46","06:58","07:10"],
            ["05:00","05:12","05:29","06:25","07:02","07:14","07:31","07:43","07:55"],
            ["05:45","05:57","06:14","07:10","07:47","07:59","08:16","08:28","08:40"],
            ["06:30","06:42","06:59","07:55","08:32","08:44","09:01","09:13","09:25"]
          ],
          ["07:22","08:07","08:52","09:37","10:10","10:55","11:40","12:25","12:58","13:43","14:28","15:13","15:46","16:31","17:16","18:01","18:34","19:19","20:04","20:49","21:22","22:07","22:52"],
          [0, 12, 17, 37, 37, 12, 17, 12, 12],
          ["23:37","23:49","00:06","00:43","-","-","-","-","-"]
        )
      },
      "50A_DOM": {
        nombre: "50A Domingo",
        columnas: ["Loteo Social", "San Martín y Trabajo", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "Ruta 22 y Riavitz", "Amancay y Muticias", "Casa Cultura", "Loteo Social"],
        filas: generarFilasPlanilla(
          [
            ["05:30","05:42","05:59","07:00","07:30","07:45","08:00","08:15","08:27"],
            ["06:10","06:22","06:39","07:34","08:04","08:19","08:34","08:49","09:01"],
            ["06:50","07:02","07:19","08:14","08:44","08:59","09:14","09:29","09:41"]
          ],
          ["08:40","09:30","10:20","11:19","12:09","12:59","13:58","14:48","15:38","16:37","17:27","18:17","19:16","20:06","20:56","21:55","22:45"],
          [0, 12, 17, 30, 30, 15, 15, 15, 12],
          ["23:35","23:47","00:04","00:34","-","-","-","-","-"]
        )
      },
      "50B_SAB": {
        nombre: "50B Sábado",
        columnas: ["Loteo Social", "Casa Cultura", "Amancay y Muticias", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "San Martín y Trabajo", "Loteo Social"],
        filas: generarFilasPlanilla(
          [
            ["04:30","04:45","05:00","05:20","05:23","06:00","06:20","06:32"],
            ["05:15","05:30","05:45","06:05","06:08","06:45","07:05","07:17"],
            ["06:00","06:15","06:30","06:50","06:53","07:30","07:50","08:02"],
            ["06:45","07:00","07:15","07:35","07:38","08:15","08:35","08:47"]
          ],
          ["06:44","07:29","08:14","08:59","09:32","10:17","11:02","11:47","12:20","13:05","13:50","14:35","15:08","15:53","16:38","17:23","17:56","18:41","19:26","20:11","20:44","21:29","22:14"],
          [0, 15, 15, 20, 37, 37, 20, 12],
          ["22:59","23:14","23:29","23:49","00:26","-","-","-"]
        )
      },
      "50B_DOM": {
        nombre: "50B Domingo",
        columnas: ["Loteo Social", "Casa Cultura", "Amancay y Muticias", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "San Martín y Trabajo", "Loteo Social"],
        filas: generarFilasPlanilla(
          [
            ["05:40","05:53","06:06","06:26","06:34","07:09","07:29","07:39"],
            ["06:20","06:33","06:46","07:06","07:14","07:49","08:09","08:19"],
            ["07:00","07:13","07:26","07:46","07:54","08:29","08:49","08:59"]
          ],
          ["07:52","08:46","09:36","10:31","11:25","12:15","13:10","14:04","14:54","15:49","16:43","17:33","18:28","19:22","20:12","21:07","22:01"],
          [0, 13, 13, 20, 35, 35, 20, 10],
          ["22:51","23:04","23:17","23:37","00:12","-","-","-"]
        )
      }
    };

    function obtenerMinutosActualesArgentina() {
      const ahora = new Date();
      const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Argentina/Buenos_Aires',
        hour: '2-digit', minute: '2-digit', weekday: 'short', hour12: false
      }).formatToParts(ahora);
      let h = 0, m = 0, wd = 'Sat';
      for (const p of fmt) {
        if (p.type === 'hour') h = parseInt(p.value, 10) % 24;
        if (p.type === 'minute') m = parseInt(p.value, 10);
        if (p.type === 'weekday') wd = p.value;
      }
      const SufijoDia = (wd === 'Sun') ? 'DOM' : 'SAB';
      const EtiquetaDia = (wd === 'Sun') ? 'Domingo' : (wd === 'Sat' ? 'Sábado' : 'Ref. Sábado');
      return { minActual: h * 60 + m, sufijoDia: SufijoDia, etiquetaDia: EtiquetaDia };
    }

    function togglePlanillas() {
      const p = document.getElementById('sched-panel');
      const b = document.getElementById('btn-sched-toggle');
      planillasAbiertas = !planillasAbiertas;
      if (planillasAbiertas) {
        p.style.display = 'block';
        b.innerText = 'Ocultar Planilla ▴';
        mostrarPlanilla(clavePlanillaActual);
      } else {
        p.style.display = 'none';
        b.innerText = 'Ver Planilla ▾';
      }
    }

    function limpiarResaltadoPlanilla() {
      puntoKeyResaltado = null;
      document.getElementById('sched-legend-box').style.display = 'none';
      document.getElementById('sched-title-text').innerText = '📅 Horarios Oficiales Fin de Semana (50A y 50B)';
      mostrarPlanilla(clavePlanillaActual);
    }

    function desplegarPlanillaConZona(puntoKey, lineaPreferida = null) {
      const punto = PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKey);
      if (!punto) return;

      puntoKeyResaltado = puntoKey;
      const infoTiempo = obtenerMinutosActualesArgentina();

      let lin = lineaPreferida;
      if (lin !== "50A" && lin !== "50B") {
        lin = (punto.cols50A && punto.cols50A.length > 0) ? "50A" : "50B";
      } else if (lin === "50B" && (!punto.cols50B || punto.cols50B.length === 0)) {
        lin = "50A";
      }

      const clave = `${lin}_${infoTiempo.sufijoDia}`;
      clavePlanillaActual = clave;

      const p = document.getElementById('sched-panel');
      const b = document.getElementById('btn-sched-toggle');
      planillasAbiertas = true;
      p.style.display = 'block';
      b.innerText = 'Ocultar Planilla ▴';

      mostrarPlanilla(clave, null);
    }

    function irALaPlanillaAbajo() {
      const sec = document.getElementById('sched-section');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function mostrarPlanilla(clave, btnEl = null) {
      clavePlanillaActual = clave;
      document.querySelectorAll('.sched-tab').forEach(t => {
        if (t.getAttribute('data-clave') === clave) {
          t.classList.add('active');
        } else {
          t.classList.remove('active');
        }
      });

      const data = PLANILLAS_INDALO[clave];
      if (!data) return;

      const es50A = clave.startsWith("50A");
      const infoTiempo = obtenerMinutosActualesArgentina();

      const colsSeleccionadas = new Set();
      const celdasProximoArribo = new Set();
      const celdasProximasParadas = new Set();
      let primeraFilaResaltada = -1;
      let primeraColResaltada = -1;

      const punto = puntoKeyResaltado ? PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKeyResaltado) : null;
      const legendBox = document.getElementById('sched-legend-box');
      const titleText = document.getElementById('sched-title-text');

      if (punto) {
        const listaCols = es50A ? punto.cols50A : punto.cols50B;
        if (listaCols && listaCols.length > 0) {
          legendBox.style.display = 'flex';
          document.getElementById('legend-zone-name').innerText = `Zona: ${punto.nombreOficial}`;
          titleText.innerText = `📅 Planilla Oficial · Zona resaltada: ${punto.nombreOficial}`;

          listaCols.forEach(cObj => {
            const cIdx = cObj.idx;
            colsSeleccionadas.add(cIdx);
            if (primeraColResaltada === -1) primeraColResaltada = cIdx;

            const candidatos = [];
            data.filas.forEach((fila, rIdx) => {
              const hhmm = fila[cIdx];
              if (!hhmm || hhmm === "-") return;
              const partes = hhmm.split(':');
              const minPaso = parseInt(partes[0], 10) * 60 + parseInt(partes[1], 10);
              let dif = minPaso - infoTiempo.minActual;
              if (dif < -720) dif += 1440;
              if (dif >= 0 && dif <= 240) {
                candidatos.push({ rIdx, dif });
              }
            });

            candidatos.sort((a, b) => a.dif - b.dif);
            const topFilas = candidatos.slice(0, 3);

            topFilas.forEach((item, orden) => {
              celdasProximoArribo.add(`${item.rIdx}_${cIdx}`);
              if (primeraFilaResaltada === -1) primeraFilaResaltada = item.rIdx;

              if (orden < 2) {
                for (let nextCol = cIdx + 1; nextCol < data.columnas.length; nextCol++) {
                  const valSig = data.filas[item.rIdx][nextCol];
                  if (valSig && valSig !== "-") {
                    celdasProximasParadas.add(`${item.rIdx}_${nextCol}`);
                  }
                }
              }
            });
          });
        } else {
          legendBox.style.display = 'none';
          titleText.innerText = '📅 Horarios Oficiales Fin de Semana (50A y 50B)';
        }
      } else {
        legendBox.style.display = 'none';
        titleText.innerText = '📅 Horarios Oficiales Fin de Semana (50A y 50B)';
      }

      let h = `<table class="sched-table"><thead><tr>`;
      data.columnas.forEach((col, cIdx) => {
        const claseCol = colsSeleccionadas.has(cIdx) ? 'col-zone-active' : '';
        const icono = colsSeleccionadas.has(cIdx) ? '📍 ' : '';
        h += `<th class="${claseCol}" id="sched-th-${cIdx}">${icono}${col}</th>`;
      });
      h += `</tr></thead><tbody>`;

      data.filas.forEach((fila, rIdx) => {
        h += `<tr id="sched-tr-${rIdx}">`;
        fila.forEach((celda, cIdx) => {
          const clases = [];
          if (colsSeleccionadas.has(cIdx)) clases.push('col-zone-active');
          if (celdasProximoArribo.has(`${rIdx}_${cIdx}`)) {
            clases.push('cell-next-arrival');
          } else if (celdasProximasParadas.has(`${rIdx}_${cIdx}`)) {
            clases.push('cell-next-stops');
          }

          const prefijo = celdasProximoArribo.has(`${rIdx}_${cIdx}`)
            ? '⏱ '
            : (celdasProximasParadas.has(`${rIdx}_${cIdx}`) ? '➔ ' : '');

          h += `<td class="${clases.join(' ')}">${prefijo}${celda}</td>`;
        });
        h += `</tr>`;
      });
      h += `</tbody></table>`;

      const tableBox = document.getElementById('sched-table-box');
      tableBox.innerHTML = h;

      if (primeraColResaltada !== -1 || primeraFilaResaltada !== -1) {
        setTimeout(() => {
          const thEl = document.getElementById(`sched-th-${Math.max(0, primeraColResaltada)}`);
          const trEl = document.getElementById(`sched-tr-${Math.max(0, primeraFilaResaltada - 1)}`);
          if (thEl) {
            tableBox.scrollLeft = Math.max(0, thEl.offsetLeft - 60);
          }
          if (trEl) {
            tableBox.scrollTop = Math.max(0, trEl.offsetTop - 38);
          }
        }, 60);
      }
    }

    function calcularHorariosPuntoOficial(puntoKey, linNom) {
      if (linNom !== "50A" && linNom !== "50B") return null;
      const punto = PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKey);
      if (!punto) return null;

      const cols = (linNom === "50A") ? punto.cols50A : punto.cols50B;
      if (!cols || cols.length === 0) return null;

      const infoTiempo = obtenerMinutosActualesArgentina();
      const planilla = PLANILLAS_INDALO[`${linNom}_${infoTiempo.sufijoDia}`];
      if (!planilla) return null;

      const resultados = [];
      for (const cInfo of cols) {
        const proximos = [];
        for (const fila of planilla.filas) {
          const hhmm = fila[cInfo.idx];
          if (!hhmm || hhmm === "-") continue;
          const partes = hhmm.split(':');
          const minPaso = parseInt(partes[0], 10) * 60 + parseInt(partes[1], 10);
          let dif = minPaso - infoTiempo.minActual;
          if (dif < -720) dif += 1440;
          if (dif >= 0 && dif <= 240) {
            proximos.push({ hora: hhmm, enMin: dif });
          }
        }
        proximos.sort((a, b) => a.enMin - b.enMin);
        if (proximos.length > 0) {
          resultados.push({
            sentidoLabel: cInfo.label,
            proximo: proximos[0],
            siguientes: proximos.slice(0, 3)
          });
        }
      }
      return { etiquetaDia: infoTiempo.etiquetaDia, bloques: resultados };
    }

    function armarHTMLHorarioProgramado(puntoKey, linNom) {
      const info = calcularHorariosPuntoOficial(puntoKey, linNom);
      if (!info || !info.bloques || info.bloques.length === 0) return '';

      let html = `<div style="margin-top:6px; padding-top:5px; border-top:1px dashed #bbb; font-size:11px; color:#222;">`;
      info.bloques.forEach(b => {
        const textoEnCuanto = b.proximo.enMin === 0 ? "¡Pasa ahora!" : `Pasa en <strong>${b.proximo.enMin} min</strong>`;
        const listaHoras = b.siguientes.map(x => `<strong>${x.hora}</strong>`).join(' · ');
        html += `
          <div style="margin-bottom:4px;">
            ⏱ <strong>${linNom} (${b.sentidoLabel}):</strong> <span style="color:#117a65; font-weight:800;">${textoEnCuanto}</span><br>
            <span style="color:#555; font-size:10.5px;">📅 Programado (${info.etiquetaDia}): ${listaHoras}</span>
          </div>
        `;
      });
      html += `<button class="btn-jump-sched" onclick="irALaPlanillaAbajo()">📅 Ver zona resaltada en planilla ▾</button></div>`;
      return html;
    }

    // Semáforos reales del corredor Plottier - Ruta 22 - Av. Mosconi - Neuquén
    const SEMAFOROS = [
      [-38.9444, -68.2304],
      [-38.9444, -68.2257],
      [-38.9506, -68.2258],
      [-38.9559, -68.2378],
      [-38.9569, -68.2263],
      [-38.9557, -68.2180],
      [-38.9556, -68.1969],
      [-38.9558, -68.1845],
      [-38.9564, -68.1676],
      [-38.9578, -68.1552],
      [-38.9579, -68.1401],
      [-38.9581, -68.1281],
      [-38.9591, -68.1172],
      [-38.9592, -68.1065],
      [-38.9594, -68.0935],
      [-38.9595, -68.0843],
      [-38.9582, -68.0748],
      [-38.9582, -68.0665],
      [-38.9582, -68.0590],
      [-38.9508, -68.0561]
    ];

    function distMts(lat1, lon1, lat2, lon2) {
      const dLat = (lat1 - lat2) * 111139;
      const dLon = (lon1 - lon2) * 111139 * 0.777;
      return Math.sqrt(dLat * dLat + dLon * dLon);
    }

    function densificarPolilinea(pts) {
      if (!pts || pts.length < 2) return pts || [];
      const res = [pts[0]];
      for (let i = 0; i < pts.length - 1; i++) {
        const p1 = pts[i], p2 = pts[i + 1];
        const d = distMts(p1[0], p1[1], p2[0], p2[1]);
        const pasos = Math.max(1, Math.ceil(d / 18));
        for (let s = 1; s <= pasos; s++) {
          const t = s / pasos;
          res.push([p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t]);
        }
      }
      return res;
    }

    function encontrarIndiceMasCercano(lat, lon, pts) {
      let minIdx = 0, minDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = distMts(lat, lon, pts[i][0], pts[i][1]);
        if (d < minDist) {
          minDist = d;
          minIdx = i;
        }
      }
      return { index: minIdx, dist: minDist };
    }

    function estaEnRutaProgramada(lat, lon, linea, sentidoCode) {
      const traza = (RUTAS_DENSAS[linea] && RUTAS_DENSAS[linea][sentidoCode]) || [];
      if (traza.length < 2) return false;
      const info = encontrarIndiceMasCercano(lat, lon, traza);
      return info.dist <= DIST_MAX_EN_RUTA_MTS;
    }

    function deslizarMarcador(bus, destLat, destLon) {
      const from = bus.marker.getLatLng();
      const to = L.latLng(destLat, destLon);
      if (from.distanceTo(to) < 1) {
        bus.simLat = destLat;
        bus.simLon = destLon;
        return;
      }
      if (from.distanceTo(to) > 2500) {
        bus.marker.setLatLng(to);
        bus.simLat = destLat;
        bus.simLon = destLon;
        return;
      }

      let start = null;
      const duration = 1200;

      function step(timestamp) {
        if (bus.enRuta) return;
        if (!start) start = timestamp;
        const progress = Math.min((timestamp - start) / duration, 1);
        const lat = from.lat + (to.lat - from.lat) * progress;
        const lon = from.lng + (to.lng - from.lng) * progress;
        bus.simLat = lat;
        bus.simLon = lon;
        bus.marker.setLatLng([lat, lon]);
        if (progress < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }

    // Calcula únicamente cuál es la próxima Parada Oficial de la planilla y en cuántos minutos llega el colectivo
    function calcularProximaParada(bus) {
      const mapaOrden = ORDEN_PARADAS_OFICIALES[bus.linea] || ORDEN_PARADAS_OFICIALES["DEFAULT"];
      const clavesOrden = mapaOrden[bus.sentido_code] || ORDEN_PARADAS_OFICIALES["DEFAULT"]["HACIA_PLOTTIER"];
      const paradasRuta = clavesOrden
        .map(k => PUNTOS_CONTROL_OFICIALES.find(p => p.key === k))
        .filter(Boolean);

      const traza = (RUTAS_DENSAS[bus.linea] && RUTAS_DENSAS[bus.linea][bus.sentido_code]) || [];

      if (traza.length > 2) {
        const posBus = encontrarIndiceMasCercano(bus.simLat, bus.simLon, traza);
        let mejorParada = null;
        let mejorIdxStop = Infinity;

        for (let i = 0; i < paradasRuta.length; i++) {
          const pc = paradasRuta[i];
          if (i === 0 && paradasRuta.length > 1) continue;
          const posStop = encontrarIndiceMasCercano(pc.lat, pc.lon, traza);
          if (posStop.index > posBus.index + 2 && posStop.index < mejorIdxStop) {
            mejorIdxStop = posStop.index;
            mejorParada = pc;
          }
        }

        if (mejorParada) {
          let distRecorridoMts = 0;
          for (let k = posBus.index; k < mejorIdxStop; k++) {
            distRecorridoMts += distMts(traza[k][0], traza[k][1], traza[k + 1][0], traza[k + 1][1]);
          }
          const velMps = Math.max(5.5, (bus.vel_kmh || 32) / 3.6);
          const minEst = Math.max(1, Math.round((distRecorridoMts / velMps) / 60));
          return `${mejorParada.nombreOficial} (~${minEst} min)`;
        }
      }

      const haciaNqn = bus.sentido_code === "HACIA_NEUQUEN";
      let mejorParadaFallback = null;
      let menorDist = Infinity;

      for (let i = 1; i < paradasRuta.length; i++) {
        const pc = paradasRuta[i];
        const deltaLon = pc.lon - bus.simLon;
        if (haciaNqn && deltaLon < -0.002) continue;
        if (!haciaNqn && deltaLon > 0.002) continue;
        const d = distMts(bus.simLat, bus.simLon, pc.lat, pc.lon);
        if (d > 60 && d < menorDist) {
          menorDist = d;
          mejorParadaFallback = pc;
        }
      }

      if (!mejorParadaFallback) {
        mejorParadaFallback = paradasRuta[paradasRuta.length - 1];
        menorDist = distMts(bus.simLat, bus.simLon, mejorParadaFallback.lat, mejorParadaFallback.lon);
      }

      const velMps = Math.max(5.5, (bus.vel_kmh || 32) / 3.6);
      const minEst = Math.max(1, Math.round(((menorDist * 1.25) / velMps) / 60));
      return `${mejorParadaFallback.nombreOficial} (~${minEst} min)`;
    }

    async function init() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.18], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      const r = await fetch('/api/static_data');
      const staticData = await r.json();
      RUTAS_GEO = staticData.trazas;
      PARADAS_LISTA = staticData.paradas_raw || [];

      for (const [lin, sentidos] of Object.entries(RUTAS_GEO)) {
        RUTAS_DENSAS[lin] = {};
        for (const [sent, pts] of Object.entries(sentidos)) {
          RUTAS_DENSAS[lin][sent] = densificarPolilinea(pts);
        }
      }

      dibujarParadas(staticData.paradas);
      pedirDatos();
      setInterval(pedirDatos, 9000);
      requestAnimationFrame(loopFisicoContinuo);
    }

    function dibujarParadas(paradas) {
      capaParadas.clearLayers();

      const mapaDestacadas = {};
      PUNTOS_CONTROL_OFICIALES.forEach(pc => {
        let mejorIdx = -1, menorD = 180;
        paradas.forEach((p, idx) => {
          const d = distMts(pc.lat, pc.lon, p[1], p[2]);
          if (d < menorD) {
            menorD = d;
            mejorIdx = idx;
          }
        });
        if (mejorIdx !== -1) {
          mapaDestacadas[mejorIdx] = pc;
        }
      });

      paradas.forEach((p, idx) => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        const puntoOficial = mapaDestacadas[idx] || null;
        const pKey = puntoOficial ? puntoOficial.key : "";

        let botones = '';
        for (const [linNom, info] of Object.entries(lineas)) {
          botones += `<button class="btn-query-stop" onclick="consultarParada(this, '${info.parada}', '${info.cod}', '${linNom}', '${pKey}')">⏱ ${linNom}</button>`;
        }

        let marker;
        if (puntoOficial) {
          const iconoDestacado = L.divIcon({
            className: 'custom-stop-featured',
            html: `<div class="stop-featured-pin" title="${puntoOficial.nombreOficial}">✓</div>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
          });
          marker = L.marker([lat, lon], { icon: iconoDestacado, zIndexOffset: 900 });
        } else {
          marker = L.circleMarker([lat, lon], {
            radius: 3.0, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.65, weight: 1.0
          });
        }

        const tituloPopup = puntoOficial ? `✅ ${puntoOficial.nombreOficial}` : `📍 ${desc}`;
        const badgeOficial = puntoOficial ? `<div class="stop-popup-badge">✓ Parada Oficial de Planilla</div>` : '';

        marker.bindPopup(`
          <div class="stop-popup-wrap" style="min-width:190px;">
            ${badgeOficial}
            <div class="stop-popup-title">${tituloPopup}</div>
            <div class="stop-popup-desc">Ref: ${id}</div>
            <div>${botones}</div>
            <div class="result-box" style="display:none;"></div>
          </div>
        `);

        if (puntoOficial) {
          marker.on('popupopen', (e) => {
            const linInicial = lineas["50A"] ? "50A" : (lineas["50B"] ? "50B" : null);
            desplegarPlanillaConZona(pKey, linInicial);

            const popupNode = e.popup.getElement();
            if (!popupNode) return;
            const box = popupNode.querySelector('.result-box');
            if (!box) return;
            let resumenProg = '';
            if (lineas["50A"]) resumenProg += armarHTMLHorarioProgramado(pKey, "50A");
            if (lineas["50B"]) resumenProg += armarHTMLHorarioProgramado(pKey, "50B");
            if (resumenProg) {
              box.style.display = 'block';
              box.innerHTML = `<div style="font-size:10.5px; color:#555; margin-bottom:2px;">Toque una línea arriba para buscar GPS en vivo:</div>` + resumenProg;
            }
          });
        }

        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(btnEl, idParada, codLinea, linNom, puntoKey) {
      const wrap = btnEl ? btnEl.closest('.stop-popup-wrap') : null;
      const box = wrap ? wrap.querySelector('.result-box') : document.querySelector('.leaflet-popup-content .result-box');

      if (puntoKey && (linNom === "50A" || linNom === "50B")) {
        desplegarPlanillaConZona(puntoKey, linNom);
      }

      const progHTML = puntoKey ? armarHTMLHorarioProgramado(puntoKey, linNom) : '';

      if (box) {
        box.style.display = 'block';
        box.innerHTML = `<em>Consultando GPS en vivo de ${linNom}...</em>${progHTML}`;
      }

      try {
        const r = await fetch(`/api/parada?id=${encodeURIComponent(idParada)}&cod=${encodeURIComponent(codLinea)}&linea=${encodeURIComponent(linNom)}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          if (box) {
            box.innerHTML = `
              <div style="color:#666;">Sin unidades cercanas reportando GPS en vivo.</div>
              ${progHTML}
            `;
          }
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:3px;"><strong>${a.ramal}</strong> (${a.sentido})<br>Arribo GPS: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span></div>`;
          });
          h += progHTML;
          if (box) box.innerHTML = h;
          pedirDatos();
        }
      } catch (e) {
        if (box) box.innerHTML = `<div style="color:#c0392b;">Error al conectar con GPS en vivo.</div>${progHTML}`;
      }
    }

    function generarHTMLPopup(bus) {
      const colorSentido = bus.sentido_code === 'HACIA_NEUQUEN' ? '#FAB387' : '#A6E3A1';
      let estadoHTML = '';

      if (bus.cabecera && bus.edad_senal >= LIMITE_DEBIL_SEG) {
        estadoHTML = `<div style="color:#b7950b; font-weight:700; margin-top:4px;">⏸️️ En ${bus.cabecera}<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad aguardando horario de salida</span></div>`;
      } else if (bus.edad_senal > LIMITE_AVERIA_SEG) {
        const minSin = Math.floor(bus.edad_senal / 60);
        estadoHTML = `<div style="color:#c0392b; font-weight:700; margin-top:4px;">🚨 Sin señal (${minSin} min)<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad detenida hasta recuperar señal</span></div>`;
      } else if (bus.edad_senal >= LIMITE_DEBIL_SEG) {
        const minDebil = Math.floor(bus.edad_senal / 60);
        const segDebil = Math.round(bus.edad_senal % 60);
        estadoHTML = `<div style="color:#d35400; font-weight:700; margin-top:4px;">⚠️ Señal débil (${minDebil}m ${segDebil}s)<br><span style="font-weight:normal; font-size:11px; color:#555;">Estimando avance sobre el recorrido</span></div>`;
      } else if (bus.enSemaforo && bus.enRuta) {
        estadoHTML = `<div style="color:#e67e22; font-weight:700; margin-top:4px;">🚦 Detenido en semáforo</div>`;
      } else {
        estadoHTML = `<div style="color:#27ae60; font-weight:700; margin-top:4px;">🟢 En movimiento (~${Math.round(bus.vel_kmh || 34)} km/h)</div>`;
      }

      const proxParada = calcularProximaParada(bus);

      return `
        <div style="font-family:sans-serif; font-size:12px; min-width:180px;">
          <strong style="font-size:14px;">Línea ${bus.linea}</strong>
          <span style="color:#666; font-size:11px;">(${bus.ramal})</span><br>
          <span style="color:${colorSentido}; font-weight:800;">${bus.sentido}</span>
          ${estadoHTML}
          <div style="margin-top:5px; padding-top:4px; border-top:1px solid #ddd; font-size:11px; color:#222;">
            📍 <strong>Próxima Parada Oficial:</strong><br>${proxParada}
          </div>
        </div>
      `;
    }

    function obtenerEstadoVisual(bus) {
      if (bus.cabecera && bus.edad_senal >= LIMITE_DEBIL_SEG) return "CABECERA";
      if (bus.edad_senal > LIMITE_AVERIA_SEG) return "AVERIA";
      if (bus.edad_senal >= LIMITE_DEBIL_SEG) return "DEBIL";
      return "NORMAL";
    }

    function construirIcono(bus) {
      let clase = "bus-marker-50b";
      if (bus.linea === "50A") clase = "bus-marker-50a";
      if (bus.linea === "50R") clase = "bus-marker-50r";
      if (bus.linea === "URBANO") clase = "bus-marker-urbano";
      if (bus.linea.includes("52")) clase = "bus-marker-52";

      const est = obtenerEstadoVisual(bus);
      let estadoClase = "";
      let iconoPrefijo = "🚌";
      if (est === "CABECERA") {
        estadoClase = "bus-cabecera";
        iconoPrefijo = "⏸️";
      } else if (est === "AVERIA") {
        estadoClase = "bus-stalled";
        iconoPrefijo = "🚨";
      } else if (est === "DEBIL") {
        estadoClase = "bus-weak";
        iconoPrefijo = "📡";
      }

      return L.divIcon({
        className: 'custom-icon',
        html: `<div class="bus-marker ${clase} ${estadoClase}">${iconoPrefijo} ${bus.linea}</div>`,
        iconSize: [72, 24],
        iconAnchor: [36, 12]
      });
    }

    let ultimoFrame = performance.now();
    function loopFisicoContinuo(ahoraMs) {
      const dt = Math.min((ahoraMs - ultimoFrame) / 1000.0, 0.25);
      ultimoFrame = ahoraMs;

      for (const id in busesSim) {
        const b = busesSim[id];

        b.edad_senal += dt;

        const nuevoEst = obtenerEstadoVisual(b);
        if (b.estadoVisual !== nuevoEst) {
          b.estadoVisual = nuevoEst;
          b.marker.setIcon(construirIcono(b));
        }

        if (!b.enRuta) {
          b.enSemaforo = false;
          continue;
        }

        if ((b.cabecera && b.edad_senal >= LIMITE_DEBIL_SEG) || b.edad_senal > LIMITE_AVERIA_SEG) {
          continue;
        }

        if (distMts(b.simLat, b.simLon, b.gpsLat, b.gpsLon) > 220) {
          continue;
        }

        if (b.pausaHastaMs && ahoraMs < b.pausaHastaMs) {
          b.enSemaforo = true;
          continue;
        } else {
          b.enSemaforo = false;
        }

        for (let s = 0; s < SEMAFOROS.length; s++) {
          const sem = SEMAFOROS[s];
          if (distMts(b.simLat, b.simLon, sem[0], sem[1]) < 20) {
            if (b.ultimoSemaforoIdx !== s) {
              b.ultimoSemaforoIdx = s;
              if (Math.random() < 0.45) {
                b.pausaHastaMs = ahoraMs + (7000 + Math.random() * 6000);
                b.enSemaforo = true;
                break;
              }
            }
          }
        }
        if (b.enSemaforo) continue;

        const factorSenal = b.edad_senal >= LIMITE_DEBIL_SEG ? 0.60 : 0.85;
        const velMps = ((b.vel_kmh || 32) / 3.6) * factorSenal;
        let avanceMts = velMps * dt;

        const traza = (RUTAS_DENSAS[b.linea] && RUTAS_DENSAS[b.linea][b.sentido_code]) || [];
        if (traza.length < 2) continue;

        const infoCercana = encontrarIndiceMasCercano(b.simLat, b.simLon, traza);
        if (infoCercana.dist > DIST_MAX_EN_RUTA_MTS) {
          b.enRuta = false;
          continue;
        }

        let idx = infoCercana.index;
        while (avanceMts > 0 && idx < traza.length - 1) {
          const sig = traza[idx + 1];
          const dSeg = distMts(b.simLat, b.simLon, sig[0], sig[1]);
          if (dSeg <= avanceMts) {
            b.simLat = sig[0];
            b.simLon = sig[1];
            avanceMts -= dSeg;
            idx++;
          } else {
            const frac = avanceMts / dSeg;
            b.simLat += (sig[0] - b.simLat) * frac;
            b.simLon += (sig[1] - b.simLon) * frac;
            avanceMts = 0;
          }
        }

        b.marker.setLatLng([b.simLat, b.simLon]);
      }

      requestAnimationFrame(loopFisicoContinuo);
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea] || !RUTAS_GEO[linea][sentidoCode]) return;

      let color = "#89B4FA";
      if (linea === "50A") color = "#A6E3A1";
      if (linea === "50R") color = "#CBA6F7";
      if (linea === "URBANO") color = "#F9E2AF";
      if (linea.includes("52")) color = "#FAB387";

      capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoCode], { color: color, weight: 5, opacity: 0.9 }));
      document.getElementById('btn-clear').style.display = 'block';
    }

    function limpiarRutas() {
      capaRuta.clearLayers();
      document.getElementById('btn-clear').style.display = 'none';
    }

    function toggleParadas() {
      const b = document.getElementById('btn-toggle-stops');
      if (mostrandoParadas) {
        map.removeLayer(capaParadas);
        b.innerText = '📍 Ver Paradas';
        mostrandoParadas = false;
      } else {
        map.addLayer(capaParadas);
        b.innerText = '📍 Ocultar Paradas';
        mostrandoParadas = true;
      }
    }

    async function pedirDatos() {
      try {
        const r = await fetch('/api/radar');
        const d = await r.json();
        document.getElementById('status').innerText = `Actualizado: ${d.timestamp}`;
        sincronizarBuses(d.buses);
      } catch (e) {}
    }

    function sincronizarBuses(buses) {
      const label = document.getElementById('bus-count');
      const enVivo = buses.filter(b => b.edad_senal <= LIMITE_AVERIA_SEG).length;
      label.innerText = buses.length > 0
        ? `🚌 ${enVivo} activos en recorrido (${buses.length} en radar)`
        : "Buscando unidades en recorrido...";

      const idsActivos = new Set();

      buses.forEach(b => {
        idsActivos.add(b.id);
        const dentroDeRuta = estaEnRutaProgramada(b.lat, b.lon, b.linea, b.sentido_code);

        if (busesSim[b.id]) {
          const sim = busesSim[b.id];
          const saltoGps = distMts(sim.gpsLat, sim.gpsLon, b.lat, b.lon);

          sim.gpsLat = b.lat;
          sim.gpsLon = b.lon;
          sim.vel_kmh = b.vel_kmh || sim.vel_kmh;
          sim.sentido = b.sentido;
          sim.sentido_code = b.sentido_code;
          sim.ramal = b.ramal;
          sim.cabecera = b.cabecera;
          sim.edad_senal = b.edad_senal;
          sim.enRuta = dentroDeRuta;

          if (!dentroDeRuta) {
            deslizarMarcador(sim, b.lat, b.lon);
          } else if (saltoGps > 15) {
            sim.pausaHastaMs = 0;
            sim.simLat = b.lat;
            sim.simLon = b.lon;
            sim.marker.setLatLng([b.lat, b.lon]);
          }

          const nuevoEst = obtenerEstadoVisual(sim);
          if (sim.estadoVisual !== nuevoEst) {
            sim.estadoVisual = nuevoEst;
            sim.marker.setIcon(construirIcono(sim));
          }

          if (sim.marker.isPopupOpen()) {
            sim.marker.getPopup().setContent(generarHTMLPopup(sim));
          }
        } else {
          const nuevoSim = {
            ...b,
            simLat: b.lat,
            simLon: b.lon,
            gpsLat: b.lat,
            gpsLon: b.lon,
            enRuta: dentroDeRuta,
            enSemaforo: false,
            pausaHastaMs: 0,
            ultimoSemaforoIdx: -1,
            estadoVisual: "NORMAL"
          };
          nuevoSim.estadoVisual = obtenerEstadoVisual(nuevoSim);
          const m = L.marker([b.lat, b.lon], { icon: construirIcono(nuevoSim) });
          m.bindPopup(() => generarHTMLPopup(nuevoSim));
          m.on('popupopen', () => {
            m.getPopup().setContent(generarHTMLPopup(nuevoSim));
            mostrarRuta(nuevoSim.linea, nuevoSim.sentido_code);
          });
          m.addTo(map);
          nuevoSim.marker = m;
          busesSim[b.id] = nuevoSim;
        }
      });

      for (let id in busesSim) {
        if (!idsActivos.has(id)) {
          map.removeLayer(busesSim[id].marker);
          delete busesSim[id];
        }
      }
    }

    init();
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
