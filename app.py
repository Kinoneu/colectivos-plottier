import os
import json
import time
import requests
import math
import re
from threading import Thread
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Buscador seguro de archivos
def find_file(filename):
    for root, dirs, files in os.walk(BASE_DIR):
        if filename in files:
            return os.path.join(root, filename)
    return None

ruta_paradas = find_file("paradas_optimizadas.json")
if ruta_paradas:
    with open(ruta_paradas, "r", encoding="utf-8") as f:
        PARADAS_RAW = json.load(f)
else:
    PARADAS_RAW = []

ruta_recorridos = find_file("urbano y r.json")
if ruta_recorridos:
    with open(ruta_recorridos, "r", encoding="utf-8") as f:
        raw_recorridos = json.load(f).get("DBCuandoLlega", {}).get("recorridos", [])
else:
    raw_recorridos = []

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

# 2. MOTOR DIRECTO A INDALO (Extracción de Token Fuerza Bruta)
class IndaloScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Origin": "https://cuandollega.smartmovepro.net",
            "Referer": "https://cuandollega.smartmovepro.net/indalo/recorridos",
            "X-Requested-With": "XMLHttpRequest"
        })
        self.token = None

    def renovar_sesion(self):
        try:
            r = self.session.get("https://cuandollega.smartmovepro.net/indalo/recorridos", timeout=10)
            html = r.text
            
            # Búsqueda a prueba de fallos y saltos de línea (re.DOTALL)
            m = re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', html, re.IGNORECASE | re.DOTALL)
            if not m:
                m = re.search(r'value=["\']([^"\']+)["\'].*?__RequestVerificationToken', html, re.IGNORECASE | re.DOTALL)
            if not m:
                m = re.search(r'(CfDJ8[A-Za-z0-9_\-]{70,})', html)
                
            if m:
                self.token = m.group(1)
                self.session.headers.update({"RequestVerificationToken": self.token})
                return True
        except Exception:
            pass
        return False

    def consultar_parada(self, parada_id, linea_cod):
        if not self.token:
            if not self.renovar_sesion():
                return [], "Fallo Token"
        try:
            r = self.session.post(
                "https://cuandollega.smartmovepro.net/indalo/recorridos?handler=Arribos",
                json={"IdentificadorParada": parada_id, "CodigoLinea": str(linea_cod)},
                timeout=10
            )
            # Si caducó la sesión (error de CSRF), renovamos y reintentamos 1 vez
            if r.status_code in [400, 401, 403, 500]:
                self.renovar_sesion()
                r = self.session.post(
                    "https://cuandollega.smartmovepro.net/indalo/recorridos?handler=Arribos",
                    json={"IdentificadorParada": parada_id, "CodigoLinea": str(linea_cod)},
                    timeout=10
                )
            if r.status_code == 200:
                data = r.json()
                arribos = data.get("arribos", [])
                return arribos, "OK"
            return [], f"Error HTTP {r.status_code}"
        except Exception as e:
            return [], "Error Timeout"

# 3. Recolector en Segundo Plano
scraper = IndaloScraper()
ESTADO_GLOBAL = {"buses": {}, "contador": 1, "diag": "Iniciando motor..."}

PARADAS_ESTRATEGICAS = [
    ("NV4120", "1013", "50A"), ("NV1244", "1013", "50A"),
    ("NV4120", "1014", "50B"), ("NV1244", "1014", "50B"),
    ("NV 4998", "1015", "50R"), ("NV6001", "1015", "50R"),
    ("NV8064", "1109", "URBANO"), ("51 00001", "1109", "URBANO"),
    ("5200001", "1079", "52 CENTRO"), ("5200001", "1080", "52 UNION")
]

def recolector_basico():
    idx = 0
    while True:
        lote = [PARADAS_ESTRATEGICAS[(idx + i) % len(PARADAS_ESTRATEGICAS)] for i in range(2)]
        idx = (idx + 2) % len(PARADAS_ESTRATEGICAS)
        ahora = time.time()
        
        buses_en_lote = 0
        ultimo_estado = ""

        for p_id, p_cod, p_lin in lote:
            arribos, diag_status = scraper.consultar_parada(p_id, p_cod)
            ultimo_estado = diag_status
            buses_en_lote += len(arribos)

            for a in arribos:
                try:
                    lat = float(str(a.get("latitud", 0)).replace(",", "."))
                    lon = float(str(a.get("longitud", 0)).replace(",", "."))
                except Exception:
                    continue
                if not lat or not lon: continue

                # Asignar ID constante
                bus_id = None
                for b_id, b in ESTADO_GLOBAL["buses"].items():
                    if b["linea"] == p_lin and math.sqrt((b["lat"]-lat)**2 + (b["lon"]-lon)**2) * 111 < 1.0:
                        bus_id = b_id
                        break
                
                if not bus_id:
                    bus_id = f"{p_lin}_{ESTADO_GLOBAL['contador']}"
                    ESTADO_GLOBAL["contador"] += 1

                ramal = str(a.get("descripcionBandera") or f"Línea {p_lin}")
                tiempo = str(a.get("tiempoRestanteArribo", ""))
                
                ESTADO_GLOBAL["buses"][bus_id] = {
                    "id": bus_id,
                    "linea": p_lin,
                    "ramal": ramal,
                    "lat": lat,
                    "lon": lon,
                    "tiempo": tiempo,
                    "last_update": ahora
                }
        
        ESTADO_GLOBAL["diag"] = f"Línea {lote[-1][2]} -> {ultimo_estado} | T. Buses en mapa: {len(ESTADO_GLOBAL['buses'])}"
        
        # Eliminar buses que no reportan hace 4 minutos
        ESTADO_GLOBAL["buses"] = {k: v for k, v in ESTADO_GLOBAL["buses"].items() if ahora - v["last_update"] < 240}
        time.sleep(3.5)

Thread(target=recolector_basico, daemon=True).start()

# 4. Rutas y Vista Web
@app.route('/api/radar')
def api_radar():
    return jsonify({
        "buses": list(ESTADO_GLOBAL["buses"].values()),
        "diag": ESTADO_GLOBAL["diag"]
    })

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
    header { padding: 15px; background: #1E1E2E; text-align: center; border-bottom: 2px solid #313244; position: relative; }
    h1 { margin: 0; font-size: 20px; color: #89B4FA; }
    #diag-badge { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.6); padding: 4px 8px; border-radius: 6px; font-size: 10px; color: #F9E2AF; border: 1px solid #F9E2AF; }
    #map { height: calc(100vh - 55px); width: 100%; }
    .bus-marker { background: #313244; color: #A6E3A1; border: 2px solid #A6E3A1; border-radius: 8px; padding: 4px; font-size: 11px; font-weight: bold; text-align: center; white-space: nowrap; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }
    .stop-marker { background: #F9E2AF; width: 8px; height: 8px; border-radius: 50%; border: 1px solid #FAB387; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>🚌 Transporte Plottier (BETA)</h1>
    <div id="diag-badge">Conectando...</div>
  </header>
  <div id="map"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map = L.map('map', { zoomControl: false }).setView([-38.955, -68.18], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

    let marcadoresBuses = {};

    fetch('/api/static_data').then(r => r.json()).then(data => {
      for (const linea in data.trazas) {
        for (const sentido in data.trazas[linea]) {
          L.polyline(data.trazas[linea][sentido], { color: '#89B4FA', weight: 4, opacity: 0.6 }).addTo(map);
        }
      }
      data.paradas.forEach(p => {
        const icon = L.divIcon({ className: 'stop-marker', iconSize: [8, 8] });
        L.marker([p[1], p[2]], { icon: icon }).bindPopup(`<b>📍 ${p[3]}</b><br>ID: ${p[0]}`).addTo(map);
      });
    });

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

    setInterval(() => {
      fetch('/api/radar').then(r => r.json()).then(data => {
        document.getElementById('diag-badge').innerText = data.diag;
        const activos = new Set();
        data.buses.forEach(b => {
          activos.add(b.id);
          const htmlIcon = `<div class="bus-marker">🚌 ${b.linea}</div>`;
          const icon = L.divIcon({ className: '', html: htmlIcon, iconSize: [60, 24], iconAnchor: [30, 12] });
          const popup = `<b>Línea ${b.linea}</b><br>${b.ramal}<br>Info API: ${b.tiempo}`;

          if (marcadoresBuses[b.id]) {
            deslizarMarcador(marcadoresBuses[b.id], b.lat, b.lon);
            marcadoresBuses[b.id].getPopup().setContent(popup);
          } else {
            const m = L.marker([b.lat, b.lon], { icon: icon }).bindPopup(popup).addTo(map);
            marcadoresBuses[b.id] = m;
          }
        });

        for (let id in marcadoresBuses) {
          if (!activos.has(id)) {
            map.removeLayer(marcadoresBuses[id]);
            delete marcadoresBuses[id];
          }
        }
      });
    }, 4000);
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
