import os
import json
import time
import requests
import math
from threading import Thread
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Cargar bases de datos estáticas
with open(os.path.join(BASE_DIR, "paradas_optimizadas.json"), "r", encoding="utf-8") as f:
    PARADAS_RAW = json.load(f)

with open(os.path.join(BASE_DIR, "urbano y r.json"), "r", encoding="utf-8") as f:
    raw_recorridos = json.load(f)["DBCuandoLlega"]["recorridos"]

MAPA_LINEAS = {
    "1013": "50A", "1014": "50B", "1015": "50R", 
    "1109": "URBANO", "1079": "52 CENTRO", "1080": "52 UNION", "1099": "TREN"
}
TRAZAS_GEO = {lin: {} for lin in MAPA_LINEAS.values()}

for rec in raw_recorridos:
    cod = str(rec.get("codigoLinea"))
    lin = MAPA_LINEAS.get(cod)
    if not lin: continue
    sentido = "HACIA_NEUQUEN" if "IDA" in rec.get("bandera", "").upper() else "HACIA_PLOTTIER"
    TRAZAS_GEO[lin][sentido] = [
        [round(float(p["latitud"]), 6), round(float(p["longitud"]), 6)]
        for p in rec.get("puntos", []) if p.get("latitud") and p.get("longitud")
    ]

# 2. Motor de Radar Base
URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"
ESTADO_GLOBAL = {"buses": {}, "contador": 1}

# Paradas estratégicas para encontrar todas las unidades
PARADAS_ESTRATEGICAS = [
    ("NV4120", "1013", "50A"), ("NV1244", "1013", "50A"),
    ("NV4120", "1014", "50B"), ("NV1244", "1014", "50B"),
    ("NV 4998", "1015", "50R"), ("NV6001", "1015", "50R"),
    ("NV8064", "1109", "URBANO"), ("51 00001", "1109", "URBANO"),
    ("5200001", "1079", "52 CENTRO"), ("5200001", "1080", "52 UNION")
]

def recolector_basico():
    """Consulta al Worker constantemente para mantener los colectivos actualizados."""
    idx = 0
    while True:
        lote = [PARADAS_ESTRATEGICAS[(idx + i) % len(PARADAS_ESTRATEGICAS)] for i in range(3)]
        idx = (idx + 3) % len(PARADAS_ESTRATEGICAS)
        ahora = time.time()

        for p_id, p_cod, p_lin in lote:
            try:
                r = requests.get(f"{URL_WORKER}parada", params={"id": p_id, "cod": p_cod, "linea": p_lin}, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    for a in data.get("arribos", []):
                        lat = float(str(a.get("lat", 0)).replace(",", "."))
                        lon = float(str(a.get("lon", 0)).replace(",", "."))
                        if not lat or not lon: continue

                        # Asignar un ID a la unidad
                        bus_id = None
                        for b_id, b in ESTADO_GLOBAL["buses"].items():
                            if b["linea"] == p_lin and math.sqrt((b["lat"]-lat)**2 + (b["lon"]-lon)**2) * 111 < 1.0:
                                bus_id = b_id
                                break
                        
                        if not bus_id:
                            bus_id = f"{p_lin}_{ESTADO_GLOBAL['contador']}"
                            ESTADO_GLOBAL["contador"] += 1

                        ramal = str(a.get("descripcionBandera") or f"Línea {p_lin}")
                        
                        ESTADO_GLOBAL["buses"][bus_id] = {
                            "id": bus_id,
                            "linea": p_lin,
                            "ramal": ramal,
                            "lat": lat,
                            "lon": lon,
                            "tiempo": str(a.get("tiempoRestanteArribo", "")),
                            "last_update": ahora
                        }
            except Exception as e:
                pass
        
        # Limpiar colectivos que llevan más de 4 minutos sin reportar
        ESTADO_GLOBAL["buses"] = {k: v for k, v in ESTADO_GLOBAL["buses"].items() if ahora - v["last_update"] < 240}
        time.sleep(5)

Thread(target=recolector_basico, daemon=True).start()

# 3. Rutas de la API y Web
@app.route('/api/radar')
def api_radar():
    return jsonify({"buses": list(ESTADO_GLOBAL["buses"].values())})

@app.route('/api/static_data')
def api_static_data():
    return jsonify({"trazas": TRAZAS_GEO, "paradas": PARADAS_RAW})

@app.route('/')
def home():
    return render_template_string(HTML_MVP)

HTML_MVP = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - BETA</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    body { margin: 0; padding: 0; background: #11111B; color: white; font-family: sans-serif; }
    header { padding: 15px; background: #1E1E2E; text-align: center; border-bottom: 2px solid #313244; }
    h1 { margin: 0; font-size: 20px; color: #89B4FA; }
    #map { height: calc(100vh - 55px); width: 100%; }
    .bus-marker { background: #313244; color: #A6E3A1; border: 2px solid #A6E3A1; border-radius: 8px; padding: 4px; font-size: 11px; font-weight: bold; text-align: center; white-space: nowrap; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }
    .stop-marker { background: #F9E2AF; width: 8px; height: 8px; border-radius: 50%; border: 1px solid #FAB387; }
  </style>
</head>
<body>
  <header><h1>🚌 Transporte Plottier (BETA Limpia)</h1></header>
  <div id="map"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map = L.map('map', { zoomControl: false }).setView([-38.955, -68.18], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

    let marcadoresBuses = {};

    // Cargar lineas y paradas estaticas
    fetch('/api/static_data').then(r => r.json()).then(data => {
      // Dibujar lineas
      for (const linea in data.trazas) {
        for (const sentido in data.trazas[linea]) {
          L.polyline(data.trazas[linea][sentido], { color: '#89B4FA', weight: 4, opacity: 0.6 }).addTo(map);
        }
      }
      // Dibujar paradas
      data.paradas.forEach(p => {
        const icon = L.divIcon({ className: 'stop-marker', iconSize: [8, 8] });
        L.marker([p[1], p[2]], { icon: icon }).bindPopup(p[3]).addTo(map);
      });
    });

    // Deslizamiento suave de los colectivos
    function deslizarMarcador(marker, lat, lon) {
      const startPos = marker.getLatLng();
      const endPos = L.latLng(lat, lon);
      if (startPos.distanceTo(endPos) < 2) return;
      if (startPos.distanceTo(endPos) > 2000) { marker.setLatLng(endPos); return; }

      let start = null;
      function animar(timestamp) {
        if (!start) start = timestamp;
        const progress = Math.min((timestamp - start) / 1000, 1);
        marker.setLatLng([
          startPos.lat + (endPos.lat - startPos.lat) * progress,
          startPos.lng + (endPos.lng - startPos.lng) * progress
        ]);
        if (progress < 1) requestAnimationFrame(animar);
      }
      requestAnimationFrame(animar);
    }

    // Actualizar radares cada 5 segundos
    setInterval(() => {
      fetch('/api/radar').then(r => r.json()).then(data => {
        const activos = new Set();
        data.buses.forEach(b => {
          activos.add(b.id);
          const htmlIcon = `<div class="bus-marker">🚌 ${b.linea}</div>`;
          const icon = L.divIcon({ className: '', html: htmlIcon, iconSize: [60, 24], iconAnchor: [30, 12] });
          const popup = `<b>Línea ${b.linea}</b><br>${b.ramal}<br>Info: ${b.tiempo}`;

          if (marcadoresBuses[b.id]) {
            deslizarMarcador(marcadoresBuses[b.id], b.lat, b.lon);
            marcadoresBuses[b.id].getPopup().setContent(popup);
          } else {
            const m = L.marker([b.lat, b.lon], { icon: icon }).bindPopup(popup).addTo(map);
            marcadoresBuses[b.id] = m;
          }
        });

        // Limpiar los que ya no estan
        for (let id in marcadoresBuses) {
          if (!activos.has(id)) {
            map.removeLayer(marcadoresBuses[id]);
            delete marcadoresBuses[id];
          }
        }
      });
    }, 5000);
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
