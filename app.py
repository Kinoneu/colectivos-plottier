import os
import re
from datetime import datetime
from flask import Flask, jsonify, render_template_string
import requests

app = Flask(__name__)

URL_PAGINA = "https://cuandollegaprueba.smartmovepro.net/indalo/recorridos"
URL_API = f"{URL_PAGINA}?handler=Arribos"

CONSULTAS = [
    {"seccion": "CASA", "parada": "NV1259", "linea": "50B", "cod": "1014"},
    {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "cod": "1014"},
    {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "cod": "1013"},
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-419,es;q=0.9",
})
csrf_token = None

def renovar_token():
    global csrf_token
    resp = session.get(URL_PAGINA, timeout=10)
    resp.raise_for_status()
    tokens = re.findall(r'CfDJ8[A-Za-z0-9_\-]{80,}', resp.text)
    if tokens:
        csrf_token = tokens[0]
    else:
        m = re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
        csrf_token = m.group(1) if m else None

def consultar_arribos(parada, cod_linea):
    global csrf_token
    if not csrf_token:
        renovar_token()
    
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://cuandollegaprueba.smartmovepro.net",
        "Referer": URL_PAGINA,
        "RequestVerificationToken": csrf_token,
        "X-Requested-With": "XMLHttpRequest"
    }
    payload = {"IdentificadorParada": parada, "CodigoLinea": str(cod_linea)}

    resp = session.post(URL_API, json=payload, headers=headers, timeout=10)
    if resp.status_code in (400, 401, 403, 500):
        renovar_token()
        headers["RequestVerificationToken"] = csrf_token
        resp = session.post(URL_API, json=payload, headers=headers, timeout=10)

    return resp.json().get("arribos", []) if resp.status_code == 200 else []

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Líneas 50A / 50B</title>
  
  <!-- Configuración PWA (Pantalla completa sin barras) -->
  <meta name="theme-color" content="#181825">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <link rel="manifest" href="/manifest.json">
  <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">
  <link rel="icon" type="image/png" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 20px 16px 90px; }
    header { margin-bottom: 20px; }
    h1 { font-size: 24px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 3px; }
    .section-title { font-size: 15px; color: #F5E0DC; text-transform: uppercase; letter-spacing: 1px; margin: 20px 0 10px; font-weight: 700; }
    .card { background: #1E1E2E; border: 1px solid #313244; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .line-tag { background: #313244; color: #89B4FA; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: 6px; }
    .stop-tag { font-size: 12px; color: #6C7086; }
    .arrival-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-top: 1px solid #2A2B3D; }
    .arrival-row:first-of-type { border-top: none; }
    .time { font-size: 16px; font-weight: 700; color: #A6E3A1; }
    .btn-gps { background: #313244; color: #CDD6F4; text-decoration: none; font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid #45475A; }
    .empty { font-size: 13px; color: #F38BA8; font-style: italic; padding: 4px 0; }
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.95); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 15px; font-weight: 700; padding: 12px 22px; border-radius: 12px; cursor: pointer; }
    .btn-refresh:disabled { opacity: 0.6; }
    .status-text { font-size: 11px; color: #A6ADC8; text-align: right; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">Líneas 50A y 50B en tiempo real</p>
  </header>

  <div id="contenido">Cargando arribos...</div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="cargarDatos()">Actualizar</button>
    <div id="status" class="status-text">Iniciando...</div>
  </div>

  <script>
    async function cargarDatos() {
      const btn = document.getElementById('btn');
      const status = document.getElementById('status');
      btn.disabled = true;
      status.innerText = "Consultando...";

      try {
        const res = await fetch('/api/arribos');
        const data = await res.json();
        render(data.items);
        status.innerText = "Actualizado: " + data.hora;
      } catch (err) {
        status.innerText = "Error de conexión";
      } finally {
        btn.disabled = false;
      }
    }

    function render(items) {
      let html = '';
      let secActual = '';

      items.forEach(item => {
        if (item.seccion !== secActual) {
          secActual = item.seccion;
          html += `<div class="section-title">📍 ${secActual}</div>`;
        }

        html += `<div class="card">
          <div class="card-header">
            <span class="line-tag">Línea ${item.linea}</span>
            <span class="stop-tag">Parada ${item.parada}</span>
          </div>`;

        if (item.arribos.length === 0) {
          html += `<div class="empty">Sin coches reportando en este momento</div>`;
        } else {
          item.arribos.forEach(c => {
            const gps = (c.lat && c.lon) ? `<a href="https://www.google.com/maps?q=${c.lat},${c.lon}" target="_blank" class="btn-gps">Ver GPS</a>` : '';
            html += `<div class="arrival-row">
              <span class="time">• ${c.tiempo}</span>
              ${gps}
            </div>`;
          });
        }
        html += `</div>`;
      });

      document.getElementById('contenido').innerHTML = html;
    }

    cargarDatos();
  </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Colectivos Plottier",
        "short_name": "Bondis 50",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#181825",
        "theme_color": "#181825",
        "icons": [{
            "src": "https://cdn-icons-png.flaticon.com/512/1048/1048314.png",
            "sizes": "512x512",
            "type": "image/png"
        }]
    })

@app.route('/api/arribos')
def api_arribos():
    resultados = []
    for item in CONSULTAS:
        try:
            arribos_raw = consultar_arribos(item["parada"], item["cod"])
            arribos_limpios = []
            for c in arribos_raw:
                arribos_limpios.append({
                    "tiempo": c.get("tiempoRestanteArribo", "Sin datos"),
                    "ramal": c.get("descripcionBandera", item["linea"]),
                    "lat": c.get("latitud"),
                    "lon": c.get("longitud")
                })
            resultados.append({**item, "arribos": arribos_limpios})
        except Exception:
            resultados.append({**item, "arribos": []})

    return jsonify({
        "hora": datetime.now().strftime("%H:%M:%S"),
        "items": resultados
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)