import os
import re
import time
import urllib3
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template_string
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
})
csrf_token = None

# Memoria caché en servidor para proteger la IP del bloqueo 500
CACHE_TTL = 25  # segundos de gracia
ultimo_cache = {
    "timestamp": 0,
    "hora": "--:--:--",
    "items": []
}

def obtener_hora_arg():
    tz_arg = timezone(timedelta(hours=-3))
    return datetime.now(tz_arg).strftime("%H:%M:%S")

def renovar_token():
    global csrf_token
    resp = session.get(URL_PAGINA, verify=False, timeout=10)
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

    resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=9)
    if resp.status_code in (400, 401, 403, 500):
        time.sleep(0.5)
        renovar_token()
        headers["RequestVerificationToken"] = csrf_token
        resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=9)

    resp.raise_for_status()
    return resp.json().get("arribos", [])

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Líneas 50A / 50B</title>
  
  <meta name="theme-color" content="#181825">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <link rel="manifest" href="/manifest.json">
  <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">
  <link rel="icon" type="image/png" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 20px 16px 95px; }
    header { margin-bottom: 16px; }
    h1 { font-size: 24px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 3px; }
    .section-title { font-size: 14px; color: #F5E0DC; text-transform: uppercase; letter-spacing: 1px; margin: 18px 0 10px; font-weight: 700; }
    .card { background: #1E1E2E; border: 1px solid #313244; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .line-tag { background: #313244; color: #89B4FA; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: 6px; }
    .stop-tag { font-size: 12px; color: #6C7086; }
    .arrival-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-top: 1px solid #2A2B3D; }
    .arrival-row:first-of-type { border-top: none; }
    .time { font-size: 16px; font-weight: 700; color: #A6E3A1; }
    .btn-gps { background: #313244; color: #CDD6F4; text-decoration: none; font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid #45475A; }
    .empty { font-size: 13px; color: #A6ADC8; font-style: italic; padding: 4px 0; }
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.95); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 15px; font-weight: 700; padding: 12px 20px; border-radius: 12px; cursor: pointer; min-width: 120px; }
    .btn-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
    .status-box { text-align: right; }
    .status-text { font-size: 12px; color: #A6ADC8; font-weight: 500; }
    .cached-hint { font-size: 10px; color: #FAB387; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">Líneas 50A y 50B en tiempo real</p>
  </header>

  <div id="contenido">Cargando arribos...</div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos(false)">Actualizar</button>
    <div class="status-box">
      <div id="status" class="status-text">Iniciando...</div>
      <div id="hint" class="cached-hint"></div>
    </div>
  </div>

  <script>
    let cooldownTimer = null;

    function iniciarCooldown(segundos) {
      const btn = document.getElementById('btn');
      btn.disabled = true;
      let restante = segundos;
      
      clearInterval(cooldownTimer);
      cooldownTimer = setInterval(() => {
        restante--;
        if (restante <= 0) {
          clearInterval(cooldownTimer);
          btn.disabled = false;
          btn.innerText = "Actualizar";
        } else {
          btn.innerText = `Espera (${restante}s)`;
        }
      }, 1000);
    }

    async function pedirDatos(forzar = false) {
      const btn = document.getElementById('btn');
      const status = document.getElementById('status');
      const hint = document.getElementById('hint');
      
      btn.disabled = true;
      status.innerText = "Consultando...";
      hint.innerText = "";

      try {
        const res = await fetch('/api/arribos' + (forzar ? '?force=1' : ''));
        const data = await res.json();
        
        if (data.items && data.items.length > 0) {
          render(data.items);
        }

        status.innerText = "Consulta: " + data.hora;
        if (data.from_cache) {
          hint.innerText = "Datos en memoria (anti-spam)";
        }

        iniciarCooldown(10);
      } catch (err) {
        status.innerText = "Error temporal";
        hint.innerText = "Reintentá en unos segundos";
        btn.disabled = false;
        btn.innerText = "Reintentar";
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

        if (!item.arribos || item.arribos.length === 0) {
          html += `<div class="empty">Sin colectivos en camino en este momento</div>`;
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

    pedirDatos(false);
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
    global ultimo_cache
    ahora = time.time()

    # Si se consultó hace menos de 25 segundos, devuelve los datos en memoria al instante
    if (ahora - ultimo_cache["timestamp"]) < CACHE_TTL and ultimo_cache["items"]:
        return jsonify({
            "hora": ultimo_cache["hora"],
            "items": ultimo_cache["items"],
            "from_cache": True
        })

    resultados = []
    hubo_fallo = False

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
            # Pausa breve entre peticiones para no saturar al servidor municipal
            time.sleep(0.35)
        except Exception as e:
            print(f"Error consultando {item['linea']} en parada {item['parada']}: {e}", flush=True)
            hubo_fallo = True
            resultados.append({**item, "arribos": []})

    hora_actual = obtener_hora_arg()

    # Si todas las consultas fallaron con 500 pero teníamos datos previos válidos, devolver respaldo
    if hubo_fallo and ultimo_cache["items"]:
        return jsonify({
            "hora": ultimo_cache["hora"],
            "items": ultimo_cache["items"],
            "from_cache": True
        })

    # Guardar en memoria
    ultimo_cache["timestamp"] = ahora
    ultimo_cache["hora"] = hora_actual
    ultimo_cache["items"] = resultados

    return jsonify({
        "hora": hora_actual,
        "items": resultados,
        "from_cache": False
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
