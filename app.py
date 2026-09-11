import os
import re
import time
import urllib3
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template_string
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

URL_PAGINA = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = f"{URL_PAGINA}?handler=Arribos"

CONSULTAS = [
    # 1. Cabeceras oficiales visibles
    {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "cod": "1014", "mostrar": True},
    {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "cod": "1013", "mostrar": True},
    
    # 2. Barrido silencioso de flota (Puntos intermedios)
    {"seccion": "BARRIDO", "parada": "NV1259", "linea": "50B", "cod": "1014", "mostrar": False},
    {"seccion": "BARRIDO", "parada": "NV1058", "linea": "50B", "cod": "1014", "mostrar": False},
    {"seccion": "BARRIDO", "parada": "NV1058", "linea": "50A", "cod": "1013", "mostrar": False},
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
})
csrf_token = None

CACHE_TTL = 18
MAX_STALE_TTL = 90

ultimo_cache = {
    "timestamp": 0,
    "hora": "--:--:--",
    "items": [],
    "buses": []
}

def obtener_hora_arg():
    tz_arg = timezone(timedelta(hours=-3))
    return datetime.now(tz_arg).strftime("%H:%M:%S")

def renovar_token():
    global csrf_token, session
    session.cookies.clear()
    resp = session.get(URL_PAGINA, verify=False, timeout=10)
    resp.raise_for_status()

    tokens = re.findall(r'CfDJ8[A-Za-z0-9_\-]{80,}', resp.text)
    if tokens:
        csrf_token = tokens[0]
    else:
        m = re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
        csrf_token = m.group(1) if m else None

    if not csrf_token:
        raise Exception("No se pudo obtener el token CSRF.")

def consultar_arribos(parada, cod_linea):
    global csrf_token
    if not csrf_token:
        renovar_token()
    
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://cuandollega.smartmovepro.net",
        "Referer": URL_PAGINA,
        "RequestVerificationToken": csrf_token,
        "X-Requested-With": "XMLHttpRequest"
    }
    payload = {"IdentificadorParada": parada, "CodigoLinea": str(cod_linea)}

    resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=8)
    if resp.status_code in (400, 401, 403, 500):
        time.sleep(0.3)
        renovar_token()
        headers["RequestVerificationToken"] = csrf_token
        resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=8)

    resp.raise_for_status()
    return resp.json().get("arribos", [])

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Líneas 50A / 50B - Plottier</title>
  
  <meta name="theme-color" content="#181825">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <link rel="manifest" href="/manifest.json">
  <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">
  <link rel="icon" type="image/png" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 95px; }
    header { margin-bottom: 12px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    
    #map-container {
      position: relative;
      margin-bottom: 16px;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #313244;
      box-shadow: 0 4px 14px rgba(0,0,0,0.4);
    }
    #map {
      height: 280px;
      width: 100%;
      background: #11111B;
    }
    .map-badge {
      position: absolute;
      top: 10px;
      left: 10px;
      z-index: 1000;
      background: rgba(24, 24, 37, 0.9);
      backdrop-filter: blur(6px);
      padding: 5px 12px;
      border-radius: 8px;
      font-size: 11px;
      color: #CDD6F4;
      border: 1px solid #313244;
      font-weight: 600;
    }

    .section-title { font-size: 14px; color: #F5E0DC; text-transform: uppercase; letter-spacing: 1px; margin: 14px 0 8px; font-weight: 700; }
    .card { background: #1E1E2E; border: 1px solid #313244; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .line-tag { background: #313244; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: 6px; }
    .line-50b { color: #89B4FA; }
    .line-50a { color: #A6E3A1; }
    .stop-tag { font-size: 12px; color: #6C7086; }
    
    .arrival-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-top: 1px solid #2A2B3D; }
    .arrival-row:first-of-type { border-top: none; }
    
    .branch-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .branch { font-size: 13px; color: #CDD6F4; font-weight: 600; }
    
    /* Distintivos de Estado */
    .badge-status {
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 6px;
      display: inline-block;
    }
    .badge-viniendo {
      background: rgba(166, 227, 161, 0.15);
      color: #A6E3A1;
      border: 1px solid rgba(166, 227, 161, 0.3);
    }
    .badge-yendose {
      background: rgba(250, 179, 135, 0.15);
      color: #FAB387;
      border: 1px solid rgba(250, 179, 135, 0.3);
    }

    .time-label { font-size: 12px; color: #A6ADC8; }
    .time-val { font-size: 15px; font-weight: 700; color: #A6E3A1; }
    
    .btn-focus { background: #313244; color: #CDD6F4; border: 1px solid #45475A; font-size: 11px; font-weight: 600; padding: 6px 12px; border-radius: 8px; cursor: pointer; }
    .empty { font-size: 13px; color: #A6ADC8; font-style: italic; padding: 4px 0; }
    
    /* Créditos de autor */
    .credits {
      text-align: center;
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid #313244;
      font-size: 12px;
      color: #6C7086;
      letter-spacing: 0.3px;
    }
    .credits .author {
      color: #CDD6F4;
      font-weight: 600;
    }
    .credits .alias-badge {
      background: #313244;
      color: #89B4FA;
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 6px;
      margin-left: 4px;
      display: inline-block;
    }

    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 15px; font-weight: 700; padding: 12px 20px; border-radius: 12px; cursor: pointer; min-width: 125px; }
    .btn-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
    .status-box { text-align: right; }
    .status-text { font-size: 12px; color: #A6ADC8; font-weight: 500; }
    .cached-hint { font-size: 10px; color: #FAB387; }

    .bus-marker {
      display: flex;
      align-items: center;
      gap: 3px;
      padding: 3px 6px;
      border-radius: 8px;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0,0,0,0.6);
    }
    .bus-marker-50b { background-color: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50a { background-color: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS y arribos a Cabecera en tiempo real</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Buscando coches...</div>
    <div id="map"></div>
  </div>

  <div id="contenido">Cargando cabeceras...</div>

  <div class="credits">
    Desarrollado por <span class="author">Ramiro Alzogaray</span>
    <span class="alias-badge">KaiLoos</span>
  </div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-box">
      <div id="status" class="status-text">Iniciando...</div>
      <div id="hint" class="cached-hint"></div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <script>
    let map, busLayer;
    let cooldownTimer = null;

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.16], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap'
      }).addTo(map);

      busLayer = L.layerGroup().addTo(map);
    }

    function centrarEn(lat, lon) {
      map.setView([lat, lon], 15, { animate: true });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

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

    async function pedirDatos() {
      const btn = document.getElementById('btn');
      const status = document.getElementById('status');
      const hint = document.getElementById('hint');
      
      btn.disabled = true;
      status.innerText = "Consultando...";
      hint.innerText = "";

      try {
        const res = await fetch('/api/arribos');
        const data = await res.json();
        
        renderTarjetas(data.items);
        actualizarMapa(data.buses);

        status.innerText = "Consulta: " + data.hora;
        if (data.from_cache) {
          hint.innerText = "Datos recientes en memoria";
        }

        iniciarCooldown(6);
      } catch (err) {
        status.innerText = "Error temporal";
        hint.innerText = "Reintentá en unos segundos";
        btn.disabled = false;
        btn.innerText = "Reintentar";
      }
    }

    function actualizarMapa(buses) {
      busLayer.clearLayers();
      const countLabel = document.getElementById('bus-count');

      if (!buses || buses.length === 0) {
        countLabel.innerText = "Sin coches activos con GPS";
        return;
      }

      countLabel.innerText = `🚌 ${buses.length} coche(s) en circulación`;

      buses.forEach(b => {
        const es50A = b.linea === "50A";
        const claseCss = es50A ? "bus-marker-50a" : "bus-marker-50b";
        
        const icon = L.divIcon({
          className: 'custom-icon',
          html: `<div class="bus-marker ${claseCss}">🚌 ${b.linea}</div>`,
          iconSize: [52, 24],
          iconAnchor: [26, 12]
        });

        const marker = L.marker([b.lat, b.lon], { icon: icon });
        const estadoColor = b.sentido === 'Viniendo' ? '#2ecc71' : '#e67e22';
        const estadoTexto = b.sentido === 'Viniendo' ? '🟢 Viniendo hacia Cabecera' : '🟠 Yéndose de Cabecera';
        const tiempoTexto = b.tiempo_cabecera 
          ? `<div style="color: #27ae60; font-weight: bold; margin-top: 4px;">⏱️ Arribo a Cabecera: ${b.tiempo_cabecera}</div>` 
          : `<div style="color: #7f8c8d; font-style: italic; margin-top: 4px;">📍 En trayecto intermedio</div>`;

        marker.bindPopup(`
          <div style="font-family: sans-serif; font-size: 13px; line-height: 1.4; min-width: 170px;">
            <strong style="color: #111; font-size: 14px;">Línea ${b.linea}</strong><br>
            <span style="color: ${estadoColor}; font-weight: 700;">${estadoTexto}</span><br>
            <span style="color: #555; font-size: 12px;">Ramal: ${b.ramal}</span>
            ${tiempoTexto}
          </div>
        `);
        busLayer.addLayer(marker);
      });
    }

    function renderTarjetas(items) {
      let html = '';
      let secActual = '';

      items.forEach(item => {
        if (item.seccion !== secActual) {
          secActual = item.seccion;
          html += `<div class="section-title">📍 ${secActual}</div>`;
        }

        const tagClase = item.linea === "50A" ? "line-50a" : "line-50b";

        html += `<div class="card">
          <div class="card-header">
            <span class="line-tag ${tagClase}">Línea ${item.linea}</span>
            <span class="stop-tag">Cabecera ${item.parada}</span>
          </div>`;

        if (!item.arribos || item.arribos.length === 0) {
          html += `<div class="empty">Sin unidades reportando hacia cabecera</div>`;
        } else {
          item.arribos.forEach(c => {
            const botonVer = (c.lat && c.lon) 
              ? `<button class="btn-focus" onclick="centrarEn(${c.lat}, ${c.lon})">Ver en Mapa</button>` 
              : '';

            const badgeClass = c.sentido === 'Viniendo' ? 'badge-viniendo' : 'badge-yendose';
            const badgeIcon = c.sentido === 'Viniendo' ? '🟢' : '🟠';

            html += `<div class="arrival-row">
              <div>
                <div class="branch-row">
                  <span class="branch">${c.ramal}</span>
                  <span class="badge-status ${badgeClass}">${badgeIcon} ${c.sentido}</span>
                </div>
                <div class="time-label">A Cabecera: <span class="time-val">${c.tiempo}</span></div>
              </div>
              ${botonVer}
            </div>`;
          });
        }
        html += `</div>`;
      });

      document.getElementById('contenido').innerHTML = html;
    }

    initMap();
    pedirDatos();
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
    antiguedad = ahora - ultimo_cache["timestamp"]

    if antiguedad < CACHE_TTL and ultimo_cache["items"]:
        return jsonify({
            "hora": ultimo_cache["hora"],
            "items": ultimo_cache["items"],
            "buses": ultimo_cache["buses"],
            "from_cache": True
        })

    resultados_visibles = []
    buses_detectados = {}
    consultas_exitosas = 0

    for item in CONSULTAS:
        try:
            arribos_raw = consultar_arribos(item["parada"], item["cod"])
            arribos_limpios = []
            es_cabecera = (item["seccion"] == "CABECERA")

            for c in arribos_raw:
                lat = c.get("latitud")
                lon = c.get("longitud")
                tiempo = c.get("tiempoRestanteArribo", "Sin datos")
                ramal = c.get("descripcionBandera", item["linea"])

                # Criterio de dirección según ramal
                ramal_upper = str(ramal).upper()
                if "IDA" in ramal_upper:
                    sentido = "Yéndose"
                elif "VUELTA" in ramal_upper:
                    sentido = "Viniendo"
                else:
                    sentido = "Viniendo" if es_cabecera else "Yéndose"

                # Guardar para las tarjetas visibles de Cabecera
                if item["mostrar"]:
                    arribos_limpios.append({
                        "tiempo": tiempo,
                        "ramal": ramal,
                        "sentido": sentido,
                        "lat": lat,
                        "lon": lon
                    })

                # Deduplicar coordenadas satelitales para el mapa
                if lat and lon and str(lat).strip() and str(lon).strip():
                    try:
                        coord_key = f"{round(float(lat), 3)}_{round(float(lon), 3)}"
                        tiempo_cab = tiempo if es_cabecera else None

                        if coord_key not in buses_detectados:
                            buses_detectados[coord_key] = {
                                "linea": item["linea"],
                                "ramal": ramal,
                                "sentido": sentido,
                                "tiempo_cabecera": tiempo_cab,
                                "lat": float(lat),
                                "lon": float(lon)
                            }
                        else:
                            # Si ya fue detectado por barrido, priorizamos los datos de Cabecera
                            if es_cabecera:
                                buses_detectados[coord_key]["tiempo_cabecera"] = tiempo_cab
                                buses_detectados[coord_key]["sentido"] = sentido
                                buses_detectados[coord_key]["ramal"] = ramal
                    except ValueError:
                        pass

            if item["mostrar"]:
                resultados_visibles.append({**item, "arribos": arribos_limpios})

            consultas_exitosas += 1
            time.sleep(0.25)
        except Exception:
            if item["mostrar"]:
                datos_previos = next((x["arribos"] for x in ultimo_cache["items"] if x["parada"] == item["parada"] and x["linea"] == item["linea"]), [])
                resultados_visibles.append({**item, "arribos": datos_previos if antiguedad < MAX_STALE_TTL else []})

    hora_actual = obtener_hora_arg()
    lista_buses = list(buses_detectados.values())

    if consultas_exitosas > 0 or antiguedad >= MAX_STALE_TTL:
        ultimo_cache["timestamp"] = ahora
        ultimo_cache["hora"] = hora_actual
        ultimo_cache["items"] = resultados_visibles
        ultimo_cache["buses"] = lista_buses
        return jsonify({
            "hora": hora_actual,
            "items": resultados_visibles,
            "buses": lista_buses,
            "from_cache": False
        })

    return jsonify({
        "hora": ultimo_cache["hora"],
        "items": ultimo_cache["items"],
        "buses": ultimo_cache["buses"],
        "from_cache": True
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
