import os
import re
import time
import math
import urllib3
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template_string
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

URL_PAGINA = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = f"{URL_PAGINA}?handler=Arribos"

# 3 consultas estratégicas (Cabeceras + Intermedia) para abarcar toda la traza sin saturar
CONSULTAS = [
    {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "cod": "1014", "mostrar": True},
    {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "cod": "1013", "mostrar": True},
    {"seccion": "BARRIDO",  "parada": "NV1058", "linea": "50B", "cod": "1014", "mostrar": False},
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
})
csrf_token = None

CACHE_TTL = 24        # Segundos mínimos entre escaneos reales a la empresa
TIEMPO_PERDIDO = 75   # Segundos sin reporte para marcar en rojo (umbral realista)
TIEMPO_EXPIRAR = 200  # Segundos para retirar definitivamente una unidad inactiva

flota_memoria = {}
ultimo_cache_cabeceras = []
ultima_hora_sync = "--:--:--"
ultimo_escaneo_ts = 0

def obtener_hora_arg():
    tz_arg = timezone(timedelta(hours=-3))
    return datetime.now(tz_arg).strftime("%H:%M:%S")

def calcular_distancia(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111.0

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
        raise Exception("No se pudo obtener token CSRF.")

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
      height: 290px;
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
    
    .credits {
      text-align: center;
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid #313244;
      font-size: 12px;
      color: #6C7086;
      letter-spacing: 0.3px;
    }
    .credits .author { color: #CDD6F4; font-weight: 600; }
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
    .cached-hint { font-size: 10px; color: #A6E3A1; }

    .leaflet-marker-icon {
      transition: transform 1.2s ease-in-out;
    }

    .bus-marker {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 3px 7px;
      border-radius: 8px;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
      box-shadow: 0 2px 8px rgba(0,0,0,0.6);
    }
    .bus-marker-50b { background-color: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50a { background-color: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    
    .bus-marker-lost {
      background-color: #381A22 !important;
      border: 2px solid #F38BA8 !important;
      color: #F38BA8 !important;
      animation: pulse-lost 1.5s infinite;
    }
    @keyframes pulse-lost {
      0% { opacity: 1; }
      50% { opacity: 0.55; }
      100% { opacity: 1; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS y arribos en vivo</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando flota...</div>
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
      <div id="hint" class="cached-hint">Auto-refresco: Activo (30s)</div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <script>
    let map;
    let marcadores = {};
    let cooldownTimer = null;

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.16], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap'
      }).addTo(map);
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
      const status = document.getElementById('status');

      try {
        const res = await fetch('/api/arribos');
        const data = await res.json();
        
        renderTarjetas(data.items);
        actualizarMapa(data.buses);

        status.innerText = "Actualizado: " + data.hora;
        iniciarCooldown(6);
      } catch (err) {
        status.innerText = "Reintentando sincronización...";
      }
    }

    function actualizarMapa(buses) {
      const countLabel = document.getElementById('bus-count');
      if (!buses || buses.length === 0) {
        countLabel.innerText = "Sin unidades reportando";
        return;
      }

      const activos = buses.filter(b => b.estado === 'activo').length;
      const perdidos = buses.filter(b => b.estado === 'perdido').length;
      countLabel.innerText = `🚌 ${activos} en camino${perdidos > 0 ? ' | ⚠️ ' + perdidos + ' con señal débil' : ''}`;

      const idsRecibidos = new Set();

      buses.forEach(b => {
        idsRecibidos.add(b.id);
        const esPerdido = (b.estado === 'perdido');
        let claseCss = (b.linea === "50A") ? "bus-marker-50a" : "bus-marker-50b";
        if (esPerdido) claseCss = "bus-marker-lost";

        const iconoHtml = `<div class="bus-marker ${claseCss}">${esPerdido ? '⚠️' : '🚌'} ${b.linea}</div>`;
        const icon = L.divIcon({
          className: 'custom-icon',
          html: iconoHtml,
          iconSize: [58, 24],
          iconAnchor: [29, 12]
        });

        const estadoColor = esPerdido ? '#e74c3c' : (b.sentido === 'Viniendo' ? '#2ecc71' : '#e67e22');
        const estadoTexto = esPerdido ? '⚠️ Señal perdida (última pos.)' : (b.sentido === 'Viniendo' ? '🟢 Viniendo hacia Cabecera' : '🟠 Yéndose de Cabecera');
        const tiempoTexto = b.tiempo_cabecera 
          ? `<div style="color: #27ae60; font-weight: bold; margin-top: 4px;">⏱️ Arribo a Cabecera: ${b.tiempo_cabecera}</div>` 
          : `<div style="color: #7f8c8d; font-style: italic; margin-top: 4px;">📍 En trayecto intermedio</div>`;

        const contenidoPopup = `
          <div style="font-family: sans-serif; font-size: 13px; line-height: 1.4; min-width: 175px;">
            <strong style="color: #111; font-size: 14px;">Línea ${b.linea}</strong><br>
            <span style="color: ${estadoColor}; font-weight: 700;">${estadoTexto}</span><br>
            <span style="color: #555; font-size: 12px;">Ramal: ${b.ramal}</span>
            ${tiempoTexto}
          </div>
        `;

        if (marcadores[b.id]) {
          marcadores[b.id].setLatLng([b.lat, b.lon]);
          marcadores[b.id].setIcon(icon);
          marcadores[b.id].getPopup().setContent(contenidoPopup);
        } else {
          const marker = L.marker([b.lat, b.lon], { icon: icon });
          marker.bindPopup(contenidoPopup);
          marker.addTo(map);
          marcadores[b.id] = marker;
        }
      });

      for (let id in marcadores) {
        if (!idsRecibidos.has(id)) {
          map.removeLayer(marcadores[id]);
          delete marcadores[id];
        }
      }
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

    // Ciclo de auto-refresco regulado a 30 segundos
    setInterval(pedirDatos, 30000);
  </script>
</body>
</html>
"""

@app.route('/ping')
def ping():
    return "OK", 200
    
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
    global flota_memoria, ultimo_cache_cabeceras, ultima_hora_sync, ultimo_escaneo_ts
    ahora = time.time()

    if (ahora - ultimo_escaneo_ts) < CACHE_TTL and ultimo_cache_cabeceras:
        return jsonify({
            "hora": ultima_hora_sync,
            "items": ultimo_cache_cabeceras,
            "buses": serializar_flota(ahora),
            "from_cache": True
        })

    nuevas_cabeceras = []
    consultas_ok = 0

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

                ramal_upper = str(ramal).upper()
                sentido = "Yéndose" if "IDA" in ramal_upper else "Viniendo"

                if item["mostrar"]:
                    arribos_limpios.append({
                        "tiempo": tiempo,
                        "ramal": ramal,
                        "sentido": sentido,
                        "lat": lat,
                        "lon": lon
                    })

                if lat and lon and str(lat).strip() and str(lon).strip():
                    try:
                        f_lat = float(lat)
                        f_lon = float(lon)
                        vincular_o_crear_colectivo(item["linea"], ramal, sentido, tiempo, es_cabecera, f_lat, f_lon, ahora)
                    except ValueError:
                        pass

            if item["mostrar"]:
                nuevas_cabeceras.append({**item, "arribos": arribos_limpios})

            consultas_ok += 1
            # Pausa de 500ms entre consultas para evitar bloqueos por ráfaga
            time.sleep(0.5)
        except Exception:
            pass

    flota_memoria = {k: v for k, v in flota_memoria.items() if (ahora - v["last_seen"]) < TIEMPO_EXPIRAR}

    if consultas_ok > 0 or not ultimo_cache_cabeceras:
        ultimo_cache_cabeceras = nuevas_cabeceras
        ultima_hora_sync = obtener_hora_arg()
        ultimo_escaneo_ts = ahora

    return jsonify({
        "hora": ultima_hora_sync,
        "items": ultimo_cache_cabeceras,
        "buses": serializar_flota(ahora),
        "from_cache": False
    })

def vincular_o_crear_colectivo(linea, ramal, sentido, tiempo, es_cabecera, lat, lon, ahora):
    bus_existente_id = None
    for bus_id, datos in flota_memoria.items():
        if datos["linea"] == linea:
            dist = calcular_distancia(datos["lat"], datos["lon"], lat, lon)
            if dist < 2.5:
                bus_existente_id = bus_id
                break

    if bus_existente_id:
        flota_memoria[bus_existente_id]["lat"] = lat
        flota_memoria[bus_existente_id]["lon"] = lon
        flota_memoria[bus_existente_id]["last_seen"] = ahora
        flota_memoria[bus_existente_id]["ramal"] = ramal
        flota_memoria[bus_existente_id]["sentido"] = sentido
        if es_cabecera:
            flota_memoria[bus_existente_id]["tiempo_cabecera"] = tiempo
    else:
        nuevo_id = f"{linea}_{round(lat, 3)}_{round(lon, 3)}"
        flota_memoria[nuevo_id] = {
            "id": nuevo_id,
            "linea": linea,
            "ramal": ramal,
            "sentido": sentido,
            "tiempo_cabecera": tiempo if es_cabecera else None,
            "lat": lat,
            "lon": lon,
            "last_seen": ahora
        }

def serializar_flota(ahora):
    lista = []
    for bus_id, datos in flota_memoria.items():
        inactivo = ahora - datos["last_seen"]
        estado = "perdido" if inactivo > TIEMPO_PERDIDO else "activo"
        lista.append({
            "id": datos["id"],
            "linea": datos["linea"],
            "ramal": datos["ramal"],
            "sentido": datos["sentido"],
            "tiempo_cabecera": datos["tiempo_cabecera"],
            "lat": datos["lat"],
            "lon": datos["lon"],
            "estado": estado
        })
    return lista

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
