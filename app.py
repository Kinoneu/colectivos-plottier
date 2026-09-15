import os
import time
import json
import re
import requests
from datetime import datetime
import zoneinfo
from threading import Thread
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Cargar paradas y trazas con rutas seguras
with open(os.path.join(BASE_DIR, "paradas_optimizadas.json"), "r", encoding="utf-8") as f:
    PARADAS_DATA = json.load(f)

with open(os.path.join(BASE_DIR, "urbano y r.json"), "r", encoding="utf-8") as f:
    raw_recorridos = json.load(f)["DBCuandoLlega"]["recorridos"]

MAPA_LINEAS = {"1013": "50A", "1014": "50B", "1015": "50R", "1016": "URBANO"}
TRAZAS_GEO = {"50A": {}, "50B": {}, "50R": {}, "URBANO": {}}

for rec in raw_recorridos:
    cod = str(rec.get("codigoLinea"))
    lin = MAPA_LINEAS.get(cod)
    if not lin:
        continue
    sentido = "HACIA_PLOTTIER" if "IDA" in rec.get("bandera", "").upper() else "HACIA_NEUQUEN"
    TRAZAS_GEO[lin][sentido] = [
        [round(p["latitud"], 6), round(p["longitud"], 6)]
        for p in rec.get("puntos", [])
        if p.get("latitud") and p.get("longitud")
    ]

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"
URL_BASE = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = "https://cuandollega.smartmovepro.net/indalo/recorridos?handler=Arribos"

PARADAS_RADAR = [
    {"linea": "50A", "cod": "1013", "parada": "NV1014"},
    {"linea": "50A", "cod": "1013", "parada": "NV1032"},
    {"linea": "50B", "cod": "1014", "parada": "NV2000"},
    {"linea": "50B", "cod": "1014", "parada": "NV1060"},
    {"linea": "50R", "cod": "1015", "parada": "NV5000"},
    {"linea": "50R", "cod": "1015", "parada": "NV5028"},
    {"linea": "URBANO", "cod": "1016", "parada": "NV7016"}
]

ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {},
    "fuente": "Iniciando...",
    "logs": []
}

CACHE_PARADAS = {}

def obtener_sesion_smp():
    s = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = s.get(URL_BASE, headers=headers, timeout=8)
        if r.status_code == 200:
            m = re.search(r'CfDJ8[A-Za-z0-9_\-]{80,}', r.text) or re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', r.text)
            token = m.group(1) if m and m.groups() else (m.group(0) if m else None)
            return s, token
    except Exception:
        pass
    return None, None

def procesar_arribos_en_radar(arribos, linea_nom, id_parada):
    global ESTADO_GLOBAL
    ahora_ts = time.time()
    for a in arribos:
        lat_raw = a.get("latitud") or a.get("lat")
        lon_raw = a.get("longitud") or a.get("lon")
        if not lat_raw or not lon_raw:
            continue
        try:
            lat = float(str(lat_raw).replace(',', '.'))
            lon = float(str(lon_raw).replace(',', '.'))
            if abs(lat) < 1 or abs(lon) < 1:
                continue
        except ValueError:
            continue

        bandera = str(a.get("descripcionBandera") or a.get("ramal") or "").upper()
        sentido = "Hacia Neuquén" if "VUELTA" in bandera else "Hacia Plottier"
        sentido_code = "HACIA_NEUQUEN" if "VUELTA" in bandera else "HACIA_PLOTTIER"

        id_unidad = f"{linea_nom}_{sentido_code}_{round(lat, 2)}_{round(lon, 2)}"

        ESTADO_GLOBAL["buses"][id_unidad] = {
            "id": id_unidad,
            "linea": linea_nom,
            "ramal": a.get("descripcionBandera") or a.get("ramal"),
            "sentido": sentido,
            "sentido_code": sentido_code,
            "tiempo_arribo": a.get("tiempoRestanteArribo") or a.get("tiempo"),
            "lat": lat,
            "lon": lon,
            "parada_detectada": id_parada,
            "updated_at": ahora_ts
        }

def recolector_segundo_plano():
    global ESTADO_GLOBAL
    print("[INICIO] Recolector arrancado correctamente.", flush=True)

    while True:
        # Intento 1: Consultar directamente a SmartMovePro
        session, token = obtener_sesion_smp()
        exito_directo = False

        if session and token:
            print("[CONEXIÓN DIRECTA] Conectado a SmartMovePro.", flush=True)
            for item in PARADAS_RADAR:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Origin": "https://cuandollega.smartmovepro.net",
                        "Referer": URL_BASE,
                        "RequestVerificationToken": token,
                        "X-Requested-With": "XMLHttpRequest"
                    }
                    payload = {"IdentificadorParada": item["parada"], "CodigoLinea": item["cod"]}
                    res = session.post(URL_API, json=payload, headers=headers, timeout=7)
                    if res.status_code == 200:
                        exito_directo = True
                        data = res.json()
                        procesar_arribos_en_radar(data.get("arribos", []), item["linea"], item["parada"])
                    elif res.status_code == 429:
                        time.sleep(10)
                except Exception:
                    break
                time.sleep(3.5)

        # Intento 2 (Fallback): Si la IP de Render fue bloqueada, consultar mediante el Cloudflare Worker
        if not exito_directo:
            print("[FALLBACK] Conectando mediante Worker Cloudflare...", flush=True)
            try:
                r_work = requests.get(URL_WORKER, timeout=10)
                if r_work.status_code == 200:
                    data = r_work.json()
                    buses_worker = data.get("buses", [])
                    for b in buses_worker:
                        procesar_arribos_en_radar([b], b.get("linea"), b.get("parada_detectada", "Worker"))
                    ESTADO_GLOBAL["fuente"] = "Cloudflare Worker (Borde)"
            except Exception as e:
                print(f"[WORKER ERROR] {e}", flush=True)
        else:
            ESTADO_GLOBAL["fuente"] = "SmartMovePro Directo"

        # Limpiar colectivos que no actualicen posición en más de 3.5 minutos
        ahora = time.time()
        ESTADO_GLOBAL["buses"] = {
            k: v for k, v in ESTADO_GLOBAL["buses"].items()
            if ahora - v["updated_at"] < 210
        }

        try:
            tz = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
            ESTADO_GLOBAL["timestamp"] = datetime.now(tz).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")

        print(f"[RADAR] {ESTADO_GLOBAL['timestamp']} | Unidades activas: {len(ESTADO_GLOBAL['buses'])} ({ESTADO_GLOBAL['fuente']})", flush=True)
        time.sleep(15)

Thread(target=recolector_segundo_plano, daemon=True).start()

@app.route('/debug')
def debug():
    return jsonify({
        "timestamp": ESTADO_GLOBAL["timestamp"],
        "fuente": ESTADO_GLOBAL["fuente"],
        "total_buses": len(ESTADO_GLOBAL["buses"]),
        "buses": list(ESTADO_GLOBAL["buses"].values())
    })

@app.route('/api/parada')
def api_parada():
    p_id = request.args.get("id")
    p_cod = request.args.get("cod")
    p_linea = request.args.get("linea")

    if not p_id or not p_cod:
        return jsonify({"arribos": []})

    cache_key = f"{p_id}_{p_cod}"
    ahora = time.time()
    if cache_key in CACHE_PARADAS and (ahora - CACHE_PARADAS[cache_key]["ts"] < 15):
        return jsonify(CACHE_PARADAS[cache_key]["data"])

    # Consultar parada individual a través del Worker (evita CORS y bloqueos de IP)
    try:
        url_parada = f"{URL_WORKER}parada?id={p_id}&cod={p_cod}&linea={p_linea}"
        r = requests.get(url_parada, timeout=8)
        if r.status_code == 200:
            data = r.json()
            arribos = data.get("arribos", [])
            procesar_arribos_en_radar(arribos, p_linea, p_id)
            resultado = {"arribos": arribos}
            CACHE_PARADAS[cache_key] = {"data": resultado, "ts": ahora}
            return jsonify(resultado)
    except Exception:
        pass

    return jsonify({"arribos": []})

@app.route('/api/radar')
def api_radar():
    return jsonify({
        "timestamp": ESTADO_GLOBAL["timestamp"],
        "buses": list(ESTADO_GLOBAL["buses"].values()),
        "total_buses": len(ESTADO_GLOBAL["buses"])
    })

@app.route('/api/static_data')
def api_static_data():
    return jsonify({
        "trazas": TRAZAS_GEO,
        "paradas": PARADAS_DATA
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
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 95px; }
    header { margin-bottom: 12px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; }
    #map { height: 420px; width: 100%; background: #11111B; }
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.9); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #CDD6F4; border: 1px solid #313244; font-weight: 700; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.9); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 10px; cursor: pointer; }
    .status-text { font-size: 12px; color: #A6ADC8; }

    .leaflet-marker-icon { transition: transform 1.8s cubic-bezier(0.25, 1, 0.5, 1) !important; cursor: pointer; }
    .bus-marker { display: flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; }
    .bus-marker-50a { background: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background: #38243E; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background: #3E3724; border: 2px solid #F9E2AF; color: #F9E2AF; }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 6px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px; }
    .result-box { margin-top: 6px; padding-top: 4px; border-top: 1px solid #ccc; font-size: 11px; color: #111; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS en vivo: 50A, 50B, 50R y Urbano</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Iniciando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRutas()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
    <div id="map"></div>
  </div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-text" id="status">Sincronizando...</div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map, capaRuta, capaParadas;
    let marcadoresBuses = {};
    let RUTAS_GEO = {};
    let mostrandoParadas = true;

    async function init() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.20], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      const r = await fetch('/api/static_data');
      const staticData = await r.json();
      RUTAS_GEO = staticData.trazas;

      dibujarParadas(staticData.paradas);
      pedirDatos();
      setInterval(pedirDatos, 15000);
    }

    function dibujarParadas(paradas) {
      capaParadas.clearLayers();
      paradas.forEach(p => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        let botones = '';
        for (const [linNom, codLin] of Object.entries(lineas)) {
          botones += `<button class="btn-query-stop" onclick="consultarParada('${id}', '${codLin}', '${linNom}')">⏱️ Ver ${linNom}</button>`;
        }

        const marker = L.circleMarker([lat, lon], {
          radius: 4.5, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.85, weight: 1.5
        });

        marker.bindPopup(`
          <div style="min-width:160px;">
            <div class="stop-popup-title">📍 Parada ${id}</div>
            <div class="stop-popup-desc">${desc}</div>
            <div>${botones}</div>
            <div id="res-${id}" class="result-box" style="display:none;"></div>
          </div>
        `);
        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(id, cod, linea) {
      const box = document.getElementById(`res-${id}`);
      box.style.display = 'block';
      box.innerHTML = '<em>Consultando arribo...</em>';

      try {
        const r = await fetch(`/api/parada?id=${id}&cod=${cod}&linea=${linea}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          box.innerHTML = `Sin arribos próximos para ${linea}.`;
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:3px;"><strong>${a.ramal}</strong> (${a.sentido})<br>Arribo: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span></div>`;
          });
          box.innerHTML = h;
          pedirDatos();
        }
      } catch (e) {
        box.innerHTML = 'Error al consultar.';
      }
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea] || !RUTAS_GEO[linea][sentidoCode]) return;

      let color = "#89B4FA";
      if (linea === "50A") color = "#A6E3A1";
      if (linea === "50R") color = "#CBA6F7";
      if (linea === "URBANO") color = "#F9E2AF";

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
        actualizarBuses(d.buses);
      } catch (e) {}
    }

    function actualizarBuses(buses) {
      const label = document.getElementById('bus-count');
      label.innerText = buses.length > 0 ? `🚌 ${buses.length} colectivos en vivo` : "Buscando unidades en recorrido...";

      const idsActivos = new Set();
      buses.forEach(b => {
        idsActivos.add(b.id);
        let clase = "bus-marker-50b";
        if (b.linea === "50A") clase = "bus-marker-50a";
        if (b.linea === "50R") clase = "bus-marker-50r";
        if (b.linea === "URBANO") clase = "bus-marker-urbano";

        const icon = L.divIcon({
          className: 'custom-icon',
          html: `<div class="bus-marker ${clase}">🚌 ${b.linea}</div>`,
          iconSize: [58, 24], iconAnchor: [29, 12]
        });

        const popup = `<strong>Línea ${b.linea}</strong><br>${b.sentido}<br><span style="color:#27ae60; font-weight:bold;">${b.tiempo_arribo || 'En camino'}</span>`;

        if (marcadoresBuses[b.id]) {
          marcadoresBuses[b.id].setLatLng([b.lat, b.lon]);
          marcadoresBuses[b.id].getPopup().setContent(popup);
        } else {
          const m = L.marker([b.lat, b.lon], { icon: icon });
          m.bindPopup(popup);
          m.on('click', () => mostrarRuta(b.linea, b.sentido_code));
          m.addTo(map);
          marcadoresBuses[b.id] = m;
        }
      });

      for (let id in marcadoresBuses) {
        if (!idsActivos.has(id)) {
          map.removeLayer(marcadoresBuses[id]);
          delete marcadoresBuses[id];
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
