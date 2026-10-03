import os
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

# 2. Agrupar paradas que estén a menos de 35 metros
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
                        g["lineas"][lin_nom] = {"cod": lin_cod, "parada": id_p}
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
                "lineas": {lin_nom: {"cod": lin_cod, "parada": id_p} for lin_nom, lin_cod in lineas.items()}
            })
    return [
        [" / ".join(g["ids"][:2]), g["lat"], g["lon"], g["desc"], g["lineas"]]
        for g in grupos
    ]

PARADAS_CLUSTERIZADAS = agrupar_paradas(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"

# Paradas terminales y estratégicas para capturar todas las unidades en ambos sentidos
PARADAS_RADAR = [
    ("NV1102", "1013", "50A"),
    ("NV1244", "1013", "50A"),
    ("NV1012", "1013", "50A"),
    ("NV4120", "1014", "50B"),
    ("NV2249", "1014", "50B"),
    ("NV2258", "1014", "50B"),
    ("NV 4998", "1015", "50R"),
    ("NV6000", "1015", "50R"),
    ("NV5019", "1015", "50R"),
    ("NV8064", "1109", "URBANO"),
    ("51 00001", "1109", "URBANO"),
    ("NV2258", "1109", "URBANO"),
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

def deducir_sentido_real(ramal_raw, sentido_worker=""):
    txt = str(ramal_raw or "").upper()
    if "IDA" in txt:
        return "Hacia Neuquén", "HACIA_NEUQUEN"
    if "VUELTA" in txt or "VTA" in txt:
        return "Hacia Plottier", "HACIA_PLOTTIER"
    sw = str(sentido_worker or "").upper()
    if "NEUQU" in sw:
        return "Hacia Plottier", "HACIA_PLOTTIER"
    if "PLOTTIER" in sw:
        return "Hacia Neuquén", "HACIA_NEUQUEN"
    return None, None

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

        sentido_fijo, code_fijo = deducir_sentido_real(d.get("ramal"), d.get("sentido"))

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

            if sentido_fijo:
                sentido = sentido_fijo
                sentido_code = code_fijo
            elif abs(delta_lon) > 0.0003:
                if delta_lon < 0:
                    sentido = "Hacia Plottier"
                    sentido_code = "HACIA_PLOTTIER"
                else:
                    sentido = "Hacia Neuquén"
                    sentido_code = "HACIA_NEUQUEN"
            else:
                sentido = bus["sentido"]
                sentido_code = bus["sentido_code"]

            # Si el GPS realmente reportó una coordenada nueva (> 12 metros)
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
                # Si sigue reportando en el sistema sin cambio de coordenadas aún, mantener señal activa
                if ahora - bus["last_gps_at"] < 120:
                    bus["last_gps_at"] = max(bus["last_gps_at"], ahora - 25)

            bus.update({
                "ramal": d.get("ramal") or bus.get("ramal"),
                "sentido": sentido,
                "sentido_code": sentido_code,
                "cabecera": detectar_cabecera(lat, lon),
                "updated_at": ahora
            })
        else:
            nuevo_id = f"{linea}_{ESTADO_GLOBAL['contador_ids']}"
            ESTADO_GLOBAL["contador_ids"] += 1

            if sentido_fijo:
                sentido = sentido_fijo
                sentido_code = code_fijo
            else:
                sentido = "Hacia Plottier"
                sentido_code = "HACIA_PLOTTIER"
                if linea in TRAZAS_GEO:
                    pts_nqn = TRAZAS_GEO[linea].get("HACIA_NEUQUEN", [])
                    pts_plo = TRAZAS_GEO[linea].get("HACIA_PLOTTIER", [])
                    d_nqn = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_nqn], default=99)
                    d_plo = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_plo], default=99)
                    if d_nqn < d_plo:
                        sentido = "Hacia Neuquén"
                        sentido_code = "HACIA_NEUQUEN"

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

    # Mantener unidades hasta 8 minutos (480s) para cubrir los tramos de +3 min (débil) y +4 min (detenido)
    ESTADO_GLOBAL["buses"] = {
        k: v for k, v in ESTADO_GLOBAL["buses"].items()
        if ahora - v["last_gps_at"] < 480
    }

def ejecutar_paso_radar(cantidad_paradas=5):
    """Ejecuta un barrido de arribos de colectivos (usado por el hilo de fondo y por /ok)."""
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
                    procesar_nuevas_posiciones([
                        {**a, "linea": p_lin}
                        for a in arribos if a.get("lat") and a.get("lon")
                    ])
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
    """
    Ventana ultraliviana para Cron-Job:
    Dispara en segundo plano la consulta de arribos de todos los colectivos como un usuario normal
    y devuelve una página blanca mínima que dice 'ok' para no saturar cron-job.org.
    """
    if time.time() - ESTADO_GLOBAL.get("ultimo_escaneo", 0) > 4:
        Thread(target=ejecutar_paso_radar, args=(8,), daemon=True).start()
    html_minimo = "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body style='background:#fff;color:#000;font-family:sans-serif;margin:8px;'>ok</body></html>"
    return Response(html_minimo, status=200, mimetype='text/html')

@app.route('/foto_perfil')
def foto_perfil():
    """Busca tu foto subida a GitHub (perfil.jpg, perfil.png, etc.) y la muestra en la web."""
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
    p_id = request.args.get("id")
    p_cod = request.args.get("cod")
    p_linea = request.args.get("linea")

    if not p_id or not p_cod:
        return jsonify({"arribos": []})

    try:
        r = requests.get(
            f"{URL_WORKER}parada",
            params={"id": p_id, "cod": p_cod, "linea": p_linea},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            arribos = data.get("arribos", [])
            for a in arribos:
                sent_real, _ = deducir_sentido_real(a.get("ramal"), a.get("sentido"))
                if sent_real:
                    a["sentido"] = sent_real

            procesar_nuevas_posiciones([
                {**a, "linea": p_linea}
                for a in arribos if a.get("lat") and a.get("lon")
            ])
            return jsonify({"arribos": arribos})
    except Exception:
        pass
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
    return render_template_string(HTML_COMPLETO)

HTML_COMPLETO = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - En Vivo</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 98px; max-width: 980px; margin: 0 auto; }
    header { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    .badge-beta { background: rgba(249, 226, 175, 0.12); color: #F9E2AF; border: 1px solid rgba(249, 226, 175, 0.4); font-size: 10px; font-weight: 800; padding: 4px 8px; border-radius: 6px; letter-spacing: 0.4px; text-transform: uppercase; }

    #map-container { position: relative; margin-bottom: 18px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; box-shadow: 0 4px 20px rgba(0,0,0,0.35); }
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

    /* Solo titila cuando lleva entre 3 y 4 minutos sin señal */
    .bus-weak { border-style: dashed !important; border-color: #F9E2AF !important; animation: pulseWeak 1.6s infinite; }
    /* Más de 4 minutos sin señal: detenido hasta recuperar */
    .bus-stalled { background: #3B1D26 !important; border-color: #F38BA8 !important; color: #F38BA8 !important; opacity: 0.88; }
    .bus-cabecera { opacity: 0.72; border-style: dotted !important; }

    @keyframes pulseWeak {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 6px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px; }
    .result-box { margin-top: 6px; padding-top: 4px; border-top: 1px solid #ccc; font-size: 11px; color: #111; }

    /* Sección Posdata / Acerca de la app */
    .about-card {
      background: #1E1E2E;
      border: 1px solid #313244;
      border-radius: 14px;
      padding: 16px;
      margin-top: 8px;
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
    <div>
      <h1>Transporte Plottier</h1>
      <p class="sub">GPS en vivo y predicción continua (50A, 50B, 50R, 51 Urbano y 52)</p>
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

    const LIMITE_DEBIL_SEG = 180;  // 3 minutos (180s) para empezar a titilar como "Señal débil"
    const LIMITE_AVERIA_SEG = 240; // 4 minutos (240s) para detenerse por pérdida de señal

    // Semáforos reales del corredor Plottier - Ruta 22 - Av. Mosconi - Neuquén
    const SEMAFOROS = [
      [-38.9444, -68.2304], // Av. del Trabajo y Favaloro
      [-38.9444, -68.2257], // Av. San Martín y Av. del Trabajo
      [-38.9506, -68.2258], // Av. San Martín y Alberdi
      [-38.9559, -68.2378], // Av. Zabaleta y Libertad
      [-38.9569, -68.2263], // Buenos Aires Norte y Riavitz
      [-38.9557, -68.2180], // Cruce Terminal ETOP
      [-38.9556, -68.1969], // Autovía y Constituyentes
      [-38.9558, -68.1845], // Autovía y Piscicultura
      [-38.9564, -68.1676], // Río Colorado (límite Plottier-Nqn)
      [-38.9578, -68.1552], // B° Valentina Sur
      [-38.9579, -68.1401], // Solalique / ETON
      [-38.9581, -68.1281], // Bejarano
      [-38.9591, -68.1172], // Anaya / Ignacio Rivas
      [-38.9592, -68.1065], // Gatica
      [-38.9594, -68.0935], // El Cholar
      [-38.9595, -68.0843], // Jumbo / Lastra
      [-38.9582, -68.0748], // Soldado Desconocido / Alcorta
      [-38.9582, -68.0665], // Lainez
      [-38.9582, -68.0590], // Av. Olascoaga
      [-38.9508, -68.0561]  // Av. Argentina / Centro
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
        const pasos = Math.max(1, Math.ceil(d / 20));
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

    function calcularProximaParada(bus) {
      let mejorNombre = null;
      let menorDist = Infinity;
      const haciaNqn = bus.sentido_code === "HACIA_NEUQUEN";

      for (const p of PARADAS_LISTA) {
        const idP = p[0], latP = p[1], lonP = p[2], descP = p[3], lineasP = p[4];
        if (!lineasP || !lineasP[bus.linea]) continue;

        const deltaLon = lonP - bus.simLon;
        if (haciaNqn && deltaLon < -0.0005) continue;
        if (!haciaNqn && deltaLon > 0.0005) continue;

        const d = distMts(bus.simLat, bus.simLon, latP, lonP);
        if (d > 25 && d < menorDist) {
          menorDist = d;
          mejorNombre = (descP && descP !== idP) ? `${descP} (${idP})` : idP;
        }
      }

      if (!mejorNombre || menorDist > 3500) return "Avanzando en recorrido";
      const velMps = Math.max(4.5, (bus.vel_kmh || 32) / 3.6);
      const minEst = Math.max(1, Math.round((menorDist / velMps) / 60));
      return `${mejorNombre} (~${minEst} min)`;
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
      paradas.forEach(p => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        let botones = '';
        for (const [linNom, info] of Object.entries(lineas)) {
          botones += `<button class="btn-query-stop" onclick="consultarParada('${info.parada}', '${info.cod}', '${linNom}')">⏱ ${linNom}</button>`;
        }

        const marker = L.circleMarker([lat, lon], {
          radius: 4.5, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.85, weight: 1.5
        });

        marker.bindPopup(`
          <div style="min-width:165px;">
            <div class="stop-popup-title">📍 ${desc}</div>
            <div class="stop-popup-desc">Ref: ${id}</div>
            <div>${botones}</div>
            <div class="result-box" style="display:none;"></div>
          </div>
        `);
        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(idParada, codLinea, linNom) {
      const box = document.querySelector('.leaflet-popup-content .result-box');
      if (box) {
        box.style.display = 'block';
        box.innerHTML = `<em>Consultando arribos de ${linNom}...</em>`;
      }

      try {
        const r = await fetch(`/api/parada?id=${encodeURIComponent(idParada)}&cod=${encodeURIComponent(codLinea)}&linea=${encodeURIComponent(linNom)}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          if (box) box.innerHTML = `Sin arribos próximos para ${linNom}.`;
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:3px;"><strong>${a.ramal}</strong> (${a.sentido})<br>Arribo: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span></div>`;
          });
          if (box) box.innerHTML = h;
          pedirDatos();
        }
      } catch (e) {
        if (box) box.innerHTML = 'Error al consultar parada.';
      }
    }

    function generarHTMLPopup(bus) {
      const colorSentido = bus.sentido_code === 'HACIA_NEUQUEN' ? '#FAB387' : '#A6E3A1';
      let estadoHTML = '';

      if (bus.cabecera && bus.edad_senal >= LIMITE_DEBIL_SEG) {
        estadoHTML = `<div style="color:#b7950b; font-weight:700; margin-top:4px;">⏸️ En ${bus.cabecera}<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad aguardando horario de salida</span></div>`;
      } else if (bus.edad_senal > LIMITE_AVERIA_SEG) {
        const minSin = Math.floor(bus.edad_senal / 60);
        estadoHTML = `<div style="color:#c0392b; font-weight:700; margin-top:4px;">🚨 Sin señal (${minSin} min)<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad detenida hasta recuperar señal</span></div>`;
      } else if (bus.edad_senal >= LIMITE_DEBIL_SEG) {
        const minDebil = Math.floor(bus.edad_senal / 60);
        const segDebil = Math.round(bus.edad_senal % 60);
        estadoHTML = `<div style="color:#d35400; font-weight:700; margin-top:4px;">⚠️ Señal débil (${minDebil}m ${segDebil}s)<br><span style="font-weight:normal; font-size:11px; color:#555;">Estimando avance sobre el recorrido</span></div>`;
      } else if (bus.enSemaforo) {
        estadoHTML = `<div style="color:#e67e22; font-weight:700; margin-top:4px;">🚦 Detenido en semáforo</div>`;
      } else {
        estadoHTML = `<div style="color:#27ae60; font-weight:700; margin-top:4px;">🟢 En movimiento (~${Math.round(bus.vel_kmh || 34)} km/h)</div>`;
      }

      const desvioHTML = bus.enDesvioMosconi
        ? `<div style="color:#8e44ad; font-size:11px; font-weight:700; margin-top:2px;">🚧 Desvío obras Av. Mosconi (traza alternativa)</div>`
        : '';

      const proxParada = calcularProximaParada(bus);

      return `
        <div style="font-family:sans-serif; font-size:12px; min-width:175px;">
          <strong style="font-size:14px;">Línea ${bus.linea}</strong>
          <span style="color:#666; font-size:11px;">(${bus.ramal})</span><br>
          <span style="color:${colorSentido}; font-weight:800;">${bus.sentido}</span>
          ${estadoHTML}
          ${desvioHTML}
          <div style="margin-top:5px; padding-top:4px; border-top:1px solid #ddd; font-size:11px; color:#222;">
            📍 <strong>Próxima:</strong> ${proxParada}
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

    // Motor de simulación continua a 60 FPS
    let ultimoFrame = performance.now();
    function loopFisicoContinuo(ahoraMs) {
      const dt = Math.min((ahoraMs - ultimoFrame) / 1000.0, 0.25);
      ultimoFrame = ahoraMs;

      for (const id in busesSim) {
        const b = busesSim[id];

        b.edad_senal += dt;

        // Actualizar icono automáticamente si cambia de estado (ej. al cruzar los 3 min o 4 min)
        const nuevoEst = obtenerEstadoVisual(b);
        if (b.estadoVisual !== nuevoEst) {
          b.estadoVisual = nuevoEst;
          b.marker.setIcon(construirIcono(b));
        }

        // 1. Si está en cabecera sin señal o supera los 4 minutos (240s) sin señal, se detiene
        if ((b.cabecera && b.edad_senal >= LIMITE_DEBIL_SEG) || b.edad_senal > LIMITE_AVERIA_SEG) {
          continue;
        }

        // 2. Verificar pausa en semáforos
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

        // 3. Calcular velocidad de avance (más conservadora cuando pasa los 3 min sin señal)
        const factorSenal = b.edad_senal >= LIMITE_DEBIL_SEG ? 0.65 : 0.90;
        const velMps = ((b.vel_kmh || 32) / 3.6) * factorSenal;
        let avanceMts = velMps * dt;

        const traza = (RUTAS_DENSAS[b.linea] && RUTAS_DENSAS[b.linea][b.sentido_code]) || [];

        // 4. Detectar si está en la zona de desvío de Av. Mosconi (al Este de Jumbo: lon > -68.088)
        const infoCercana = traza.length > 0 ? encontrarIndiceMasCercano(b.simLat, b.simLon, traza) : { index: 0, dist: 999 };
        b.enDesvioMosconi = (b.simLon > -68.088 && infoCercana.dist > 45);

        if (traza.length > 1 && !b.enDesvioMosconi && infoCercana.dist < 180) {
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
        } else {
          const dirLon = b.sentido_code === "HACIA_NEUQUEN" ? 1 : -1;
          const dLonGrados = (avanceMts / (111139 * 0.777)) * dirLon;
          b.simLon += dLonGrados;
        }

        if (b.edad_senal < 15) {
          const err = distMts(b.simLat, b.simLon, b.gpsLat, b.gpsLon);
          if (err > 15 && err < 600) {
            b.simLat += (b.gpsLat - b.simLat) * 0.04;
            b.simLon += (b.gpsLon - b.simLon) * 0.04;
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

          if (saltoGps > 25) {
            sim.pausaHastaMs = 0;
            if (distMts(sim.simLat, sim.simLon, b.lat, b.lon) > 220) {
              sim.simLat = b.lat;
              sim.simLon = b.lon;
            }
          }

          const nuevoEst = obtenerEstadoVisual(sim);
          if (sim.estadoVisual !== nuevoEst) {
            sim.estadoVisual = nuevoEst;
            sim.marker.setIcon(construirIcono(sim));
          }

          sim.marker.getPopup().setContent(generarHTMLPopup(sim));
          sim.marker.off('click').on('click', () => {
            sim.marker.getPopup().setContent(generarHTMLPopup(sim));
            mostrarRuta(sim.linea, sim.sentido_code);
          });
        } else {
          const nuevoSim = {
            ...b,
            simLat: b.lat,
            simLon: b.lon,
            gpsLat: b.lat,
            gpsLon: b.lon,
            enSemaforo: false,
            enDesvioMosconi: false,
            pausaHastaMs: 0,
            ultimoSemaforoIdx: -1,
            estadoVisual: "NORMAL"
          };
          nuevoSim.estadoVisual = obtenerEstadoVisual(nuevoSim);
          const m = L.marker([b.lat, b.lon], { icon: construirIcono(nuevoSim) });
          m.bindPopup(generarHTMLPopup(nuevoSim));
          m.on('click', () => {
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
