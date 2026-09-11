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

CACHE_TTL = 24
TIEMPO_PERDIDO = 75
TIEMPO_EXPIRAR = 200

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
      height: 300px;
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
    .btn-clear-route {
      position: absolute;
      bottom: 10px;
      right: 10px;
      z-index: 1000;
      background: rgba(24, 24, 37, 0.9);
      border: 1px solid #45475A;
      color: #CDD6F4;
      font-size: 11px;
      font-weight: 700;
      padding: 6px 12px;
      border-radius: 8px;
      cursor: pointer;
      display: none;
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
    
    .card-actions { display: flex; flex-direction: column; gap: 5px; align-items: flex-end; }
    .btn-action { background: #313244; color: #CDD6F4; border: 1px solid #45475A; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 8px; cursor: pointer; text-decoration: none; }
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
      cursor: pointer;
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
    <p class="sub">GPS, recorridos y arribos en vivo</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando flota...</div>
    <button class="btn-clear-route" id="btn-clear" onclick="limpiarRuta()">✕ Quitar recorrido</button>
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
    // Traza oficial extraída de Smart Move Pro para la línea 50B
    const TRAZAS_METRICAS = {
      "50B": {
        "IDA": [[-7576123.127717475,-4713953.225682237],[-7576127.135219142,-4713960.668571745],[-7576140.270919057,-4714625.541017488],[-7575523.672259552,-4714622.5350375585],[-7575533.913652705,-4715537.968661558],[-7578334.266763101,-4715525.657356469],[-7578412.190406656,-4715517.9270097455],[-7578498.129053549,-4715523.939501133],[-7578494.566829843,-4715600.956967883],[-7579108.493821568,-4715589.933986044],[-7579115.72958847,-4715842.177166955],[-7583422.0127703175,-4715796.366361502],[-7583523.090867958,-4715778.757888199],[-7583546.913238986,-4715779.473679201],[-7583639.5310553275,-4715757.141023744],[-7583717.454698882,-4715733.949472043],[-7583945.325696536,-4715679.120273622],[-7584124.772715694,-4715657.360465009],[-7584513.611697037,-4715650.345799814],[-7584585.078810125,-4715654.067866457],[-7584684.821073875,-4715642.042732994],[-7586734.21289938,-4715629.015521161],[-7586895.51484154,-4715621.7145636035],[-7587297.155564321,-4715619.280912253],[-7588442.187846622,-4715419.723488214],[-7588664.270230753,-4715194.25981618],[-7590284.970697214,-4713564.914808015],[-7590591.87853333,-4714429.581617774],[-7590632.510147468,-4714417.701074614],[-7590624.4951441325,-4713756.849877528],[-7594854.635794276,-4713713.624809864],[-7594851.518848535,-4712383.6136334315],[-7596173.103843232,-4712371.878595528],[-7596505.837801212,-4712371.306155002],[-7596507.062315612,-4712007.097415341],[-7596821.09459914,-4712010.675040777],[-7596824.768142336,-4711714.451925238],[-7597492.351128625,-4711704.291768824],[-7597495.690713347,-4711684.114586941],[-7597586.861376307,-4711683.685285635],[-7597684.154611261,-4711690.840309779],[-7597727.45789318,-4711685.545591426],[-7597782.672360612,-4711685.259390514],[-7597844.788636475,-4711680.966377784],[-7597998.52085326,-4711678.390571015],[-7598051.731569858,-4711679.249173199],[-7598168.394396211,-4711676.244065874],[-7598169.618910611,-4711685.545591426],[-7598514.820651559,-4711685.974892813],[-7598512.816900725,-4712308.0516757555],[-7598463.279727323,-4712301.611762196],[-7598446.470484212,-4712292.166563034],[-7598173.626412278,-4712256.103156181],[-7598125.425072765,-4712247.65975801],[-7598058.85601727,-4712240.361233048],[-7597865.271422781,-4712214.744883052],[-7597575.506788245,-4712170.810846718],[-7597547.676915548,-4712165.9451996675],[-7597528.752602113,-4712163.798591416],[-7597513.947109837,-4712164.943449095],[-7597508.492454789,-4712161.938197968],[-7597509.049052242,-4712127.8787473785],[-7597488.900224409,-4712119.864775614],[-7597477.5456363475,-4712111.850810179],[-7597471.200425373,-4712047.309997799],[-7596829.220921968,-4712055.46701795],[-7596829.220921968,-4712382.75497166],[-7596173.437801706,-4712373.16658683],[-7596170.654814434,-4713035.3588711675],[-7595380.954346748,-4713041.083652457],[-7595378.505317951,-4713714.054197047],[-7594863.763992522,-4713715.342358708],[-7594864.097950994,-4714610.94055188],[-7595153.1946685845,-4714615.807371415],[-7595602.257494444,-4714856.431565999],[-7595629.085491726,-4714867.740041546],[-7595630.866603578,-4714928.720139591],[-7595924.750059273,-4714929.292724408],[-7596190.469683797,-4714997.287401224],[-7596213.178859917,-4715768.307345327],[-7596826.437934698,-4715759.288392326],[-7596826.437934698,-4715656.644682625],[-7597004.326480986,-4715716.341107085],[-7597005.550995384,-4715740.248406765],[-7597262.2537411535,-4715780.332628469]],
        "VUELTA": [[-7597262.2537411535,-4715780.332628469],[-7597261.585824208,-4715793.78950984],[-7597226.854143082,-4716016.403276067],[-7597064.327686524,-4715986.482556415],[-7596989.4096692195,-4715979.467663623],[-7596961.802435502,-4715989.202618192],[-7596826.66057368,-4715988.773134706],[-7596820.649321177,-4716600.519214987],[-7596475.558899717,-4716534.374985973],[-7596227.093796266,-4716495.71946742],[-7596221.97309969,-4716454.200741217],[-7596218.633514967,-4716119.909604224],[-7596222.084419181,-4715995.358550169],[-7594918.31054301,-4715996.933324063],[-7594907.623871894,-4715503.468414098],[-7594600.827355268,-4715459.233828643],[-7594473.700496783,-4715407.8417855],[-7594294.253477624,-4715367.759035632],[-7594121.374308422,-4715348.004024316],[-7593282.804584275,-4715345.999894883],[-7593272.340552142,-4715328.678506993],[-7588935.667149306,-4715362.032941436],[-7588411.018389199,-4715449.356229109],[-7587310.959181179,-4715648.771079722],[-7584045.624557742,-4715682.126566638],[-7583538.452957686,-4715799.945323227],[-7580364.734275171,-4715848.762487246],[-7580187.402326336,-4715861.64682192],[-7580145.65751729,-4715862.362618769],[-7580125.286050473,-4715872.240620467],[-7579728.988663251,-4715861.074184476],[-7579426.756245745,-4715880.1143968245],[-7579110.608891894,-4715874.388013413],[-7579107.046668188,-4715591.079230352],[-7578495.012107806,-4715600.098033803],[-7578493.787593408,-4715677.688705831],[-7577255.692216804,-4715681.840252981],[-7577108.193891504,-4715689.284410742],[-7576301.684180708,-4715700.021186369],[-7576299.3464714,-4715234.198730027],[-7575988.765092087,-4715237.920643987],[-7575978.078420971,-4713612.4330702275],[-7576128.916330996,-4713616.011261632],[-7576123.127717475,-4713953.225682237]]
      }
    };

    // Conversión matemática EPSG:3857 a WGS84 (Lat, Lon)
    function mercatorALatLon(x, y) {
      const lon = (x / 20037508.34) * 180;
      let lat = (y / 20037508.34) * 180;
      lat = 180 / Math.PI * (2 * Math.atan(Math.exp(lat * Math.PI / 180)) - Math.PI / 2);
      return [lat, lon];
    }

    let map;
    let capaRuta = null;
    let marcadores = {};
    let cooldownTimer = null;

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.16], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap'
      }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
    }

    function mostrarRuta(linea, sentido) {
      capaRuta.clearLayers();
      const sentidoClave = (sentido === "Yéndose" || sentido === "IDA") ? "IDA" : "VUELTA";

      if (TRAZAS_METRICAS[linea] && TRAZAS_METRICAS[linea][sentidoClave]) {
        const puntosMercator = TRAZAS_METRICAS[linea][sentidoClave];
        const puntosLatLon = puntosMercator.map(p => mercatorALatLon(p[0], p[1]));

        const color = (linea === "50A") ? "#A6E3A1" : "#89B4FA";
        const poliLinea = L.polyline(puntosLatLon, {
          color: color,
          weight: 4,
          opacity: 0.85,
          lineJoin: 'round'
        });

        capaRuta.addLayer(poliLinea);
        document.getElementById('btn-clear').style.display = 'block';
      }
    }

    function limpiarRuta() {
      capaRuta.clearLayers();
      document.getElementById('btn-clear').style.display = 'none';
    }

    function centrarEn(lat, lon, linea, sentido) {
      map.setView([lat, lon], 15, { animate: true });
      if (linea && sentido) {
        mostrarRuta(linea, sentido);
      }
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
            <div style="margin-top: 8px;">
              <button style="background: #313244; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; cursor: pointer; width: 100%;" onclick="mostrarRuta('${b.linea}', '${b.sentido}')">🗺️ Ver recorrido</button>
            </div>
          </div>
        `;

        if (marcadores[b.id]) {
          marcadores[b.id].setLatLng([b.lat, b.lon]);
          marcadores[b.id].setIcon(icon);
          marcadores[b.id].getPopup().setContent(contenidoPopup);
        } else {
          const marker = L.marker([b.lat, b.lon], { icon: icon });
          marker.bindPopup(contenidoPopup);
          
          // Al tocar el coche en el mapa, dibuja su ruta automáticamente
          marker.on('click', () => {
            mostrarRuta(b.linea, b.sentido);
          });

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
              ? `<button class="btn-action" onclick="centrarEn(${c.lat}, ${c.lon}, '${item.linea}', '${c.sentido}')">Ver en Mapa</button>` 
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
              <div class="card-actions">
                ${botonVer}
              </div>
            </div>`;
          });
        }
        html += `</div>`;
      });

      document.getElementById('contenido').innerHTML = html;
    }

    initMap();
    pedirDatos();

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
