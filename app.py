import os
import re
import time
import math
import urllib3
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template_string, request
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

URL_PAGINA = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = f"{URL_PAGINA}?handler=Arribos"

# Paradas fijas de cabecera para mantener los colectivos vivos en el mapa
CONSULTAS_CABECERA = [
    {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "cod": "1014", "mostrar": True},
    {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "cod": "1013", "mostrar": True},
    {"seccion": "BARRIDO",  "parada": "NV1058", "linea": "50B", "cod": "1014", "mostrar": False},
    {"seccion": "BARRIDO",  "parada": "NV1032", "linea": "50A", "cod": "1013", "mostrar": False},
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
})
csrf_token = None

CACHE_TTL = 18
TIEMPO_PERDIDO = 85
TIEMPO_EXPIRAR = 220

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

    try:
        resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=8)
        if resp.status_code in (400, 401, 403, 500):
            time.sleep(0.3)
            renovar_token()
            headers["RequestVerificationToken"] = csrf_token
            resp = session.post(URL_API, json=payload, headers=headers, verify=False, timeout=8)

        resp.raise_for_status()
        return resp.json().get("arribos", [])
    except Exception:
        return []

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-CE85R9NET5"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-CE85R9NET5');
  </script>

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - Colectivos y Paradas</title>
  
  <meta name="theme-color" content="#181825">
  <link rel="manifest" href="/manifest.json">
  <link rel="icon" type="image/png" href="https://cdn-icons-png.flaticon.com/512/1048/1048314.png">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 95px; }
    header { margin-bottom: 12px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    
    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; box-shadow: 0 4px 14px rgba(0,0,0,0.4); }
    #map { height: 350px; width: 100%; background: #11111B; }
    
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.9); backdrop-filter: blur(6px); padding: 5px 12px; border-radius: 8px; font-size: 11px; color: #CDD6F4; border: 1px solid #313244; font-weight: 600; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.9); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }

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
    
    .badge-status { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; display: inline-block; }
    .badge-neuquen { background: rgba(250, 179, 135, 0.15); color: #FAB387; border: 1px solid rgba(250, 179, 135, 0.3); }
    .badge-plottier { background: rgba(166, 227, 161, 0.15); color: #A6E3A1; border: 1px solid rgba(166, 227, 161, 0.3); }

    .time-label { font-size: 12px; color: #A6ADC8; }
    .time-val { font-size: 15px; font-weight: 700; color: #A6E3A1; }
    .no-gps-hint { font-size: 11px; color: #6C7086; font-style: italic; margin-top: 2px; }
    
    .btn-action { background: #313244; color: #CDD6F4; border: 1px solid #45475A; font-size: 11px; font-weight: 600; padding: 6px 12px; border-radius: 8px; cursor: pointer; }
    .empty { font-size: 13px; color: #A6ADC8; font-style: italic; padding: 4px 0; }
    
    .credits { text-align: center; margin-top: 24px; padding-top: 16px; border-top: 1px solid #313244; font-size: 12px; color: #6C7086; letter-spacing: 0.3px; }
    .credits .author { color: #CDD6F4; font-weight: 600; }
    .credits .alias-badge { background: #313244; color: #89B4FA; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 6px; margin-left: 4px; display: inline-block; }

    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 15px; font-weight: 700; padding: 12px 20px; border-radius: 12px; cursor: pointer; min-width: 125px; }
    .btn-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
    .status-box { text-align: right; }
    .status-text { font-size: 12px; color: #A6ADC8; font-weight: 500; }
    .cached-hint { font-size: 10px; color: #A6E3A1; }

    .leaflet-marker-icon { transition: transform 1.2s ease-in-out; cursor: pointer; }
    .bus-marker { display: flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.6); }
    .bus-marker-50b { background-color: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50a { background-color: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-lost { background-color: #381A22 !important; border: 2px solid #F38BA8 !important; color: #F38BA8 !important; animation: pulse-lost 1.5s infinite; }
    @keyframes pulse-lost { 0% { opacity: 1; } 50% { opacity: 0.55; } 100% { opacity: 1; } }

    /* Popups modernos */
    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; margin-bottom: 2px; }
    .stop-popup-desc { font-size: 11px; color: #666; margin-bottom: 8px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 5px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer; margin-right: 4px; margin-top: 4px; }
    .btn-query-stop:hover { background: #313244; }
    .result-box { margin-top: 8px; padding-top: 6px; border-top: 1px solid #ddd; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS en vivo y paradas interactivas</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando flota...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRuta()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
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
    // Listado oficial de paradas extraído de Smart Move Pro
    const TODAS_LAS_PARADAS = [
      ["NV1008", -38.959017, -68.106748, "Ruta 22 / Acceso Este"],
      ["NV1010", -38.958888, -68.117712, "Ruta 22 y Bejarano"],
      ["NV1025", -38.957974, -68.141026, "Ruta 22 y Saavedra"],
      ["NV1143", -38.957799, -68.155489, "Ruta 22 y Solalique"],
      ["NV1029", -38.955654, -68.192332, "Ruta 22 y Río Colorado"],
      ["NV1027", -38.956455, -68.167527, "Ruta 22 y Crouzeilles"],
      ["NV1012", -38.956568, -68.167666, "Ruta 22 / Terminal Nqn"],
      ["NV1013", -38.955613, -68.178095, "Ruta 22 y Gatica"],
      ["NV1028", -38.955880, -68.185664, "Ruta 22 / Mayor Buratovich"],
      ["NV1030", -38.955804, -68.196961, "Ruta 22 / La Herradura"],
      ["NV1031", -38.955563, -68.208768, "Ruta 22 y Constituyentes"],
      ["NV1032", -38.955388, -68.218424, "Ruta 22 / Acceso Plottier"],
      ["NV1026", -38.957840, -68.155897, "Ruta 22 / Aeropuerto"],
      ["NV1011", -38.957999, -68.139772, "Ruta 22 y O'Connor"],
      ["NV1009", -38.958909, -68.117123, "Ruta 22 y Anaya"],
      ["NV1014", -38.946381, -68.057601, "Cabecera Neuquén (Mitre)"],
      ["NV1015", -38.949342, -68.057693, "Sarmiento y San Luis"],
      ["NV1016", -38.950777, -68.056394, "Láinez y Alcorta"],
      ["NV1017", -38.950693, -68.053841, "Perito Moreno y Misiones"],
      ["NV1018", -38.951683, -68.052191, "Bahía Blanca"],
      ["NV1019", -38.955511, -68.052243, "Ruta 22 y Tierra del Fuego"],
      ["NV1021", -38.957124, -68.060420, "Ruta 22 y La Pampa"],
      ["NV1023", -38.957960, -68.147140, "Ruta 22 y El Cholar"],
      ["NV1024", -38.955619, -68.195944, "Ruta 22 y Futaleufú"],
      ["NV1034", -38.958992, -68.248224, "San Martín y Candolle"],
      ["NV1116", -38.959502, -68.088995, "Ruta 22 y Leguizamón"],
      ["NV1117", -38.959225, -68.095626, "Ruta 22 y Gatica"],
      ["NV1050", -38.960227, -68.231994, "San Martín y Martellotta"],
      ["NV1035", -38.964104, -68.239780, "Belgrano y Zabaleta"],
      ["NV1038", -38.964520, -68.243109, "Belgrano y Libertad"],
      ["NV1039", -38.962051, -68.243420, "Batilana y Perito Moreno"],
      ["NV1040", -38.960381, -68.244661, "San Martín y Chivilcoy"],
      ["NV1041", -38.960362, -68.227848, "San Martín y Río Colorado"],
      ["NV1042", -38.960357, -68.229405, "San Martín y Percy Clark"],
      ["NV1043", -38.960336, -68.233364, "San Martín y Bachmann"],
      ["NV1044", -38.960239, -68.236177, "San Martín y Buratovich"],
      ["NV1046", -38.961257, -68.238108, "Belgrano y Constituyentes"],
      ["NV1047", -38.963159, -68.238079, "Belgrano y Güemes"],
      ["NV1048", -38.963915, -68.238462, "Belgrano y San Carlos"],
      ["NV1049", -38.964228, -68.240999, "Belgrano y Santa Cruz"],
      ["NV1051", -38.960069, -68.247066, "San Martín y Maestros Neuquinos"],
      ["NV1052", -38.959130, -68.249539, "San Martín y Posta de Halada"],
      ["NV1058", -38.958794, -68.124248, "Ruta 22 / Intermedia San Martín"],
      ["NV1059", -38.958877, -68.118315, "Ruta 22 y Drury"],
      ["NV1060", -38.958078, -68.134464, "Ruta 22 y รlvarez"],
      ["NV1062", -38.955871, -68.198951, "Ruta 22 y Fotheringham"],
      ["NV1063", -38.955454, -68.211289, "Ruta 22 y Roca"],
      ["NV1066", -38.956680, -68.226224, "Ruta 22 y Godoy"],
      ["NV1069", -38.957731, -68.226288, "Ruta 22 y Pellegrini"],
      ["NV1070", -38.957718, -68.159731, "Ruta 22 y Casimiro Gómez"],
      ["NV1071", -38.955713, -68.175137, "Ruta 22 y Chaco"],
      ["NV1136", -38.959289, -68.085507, "Ruta 22 y Jujuy"],
      ["NV2021", -38.959249, -68.090370, "Ruta 22 y Laínez"],
      ["NV6043", -38.959504, -68.089109, "Ruta 22 y Misiones"],
      ["AXION", -38.959108, -68.070216, "Mosconi y Chubut"],
      ["GATICA 299", -38.959279, -68.073504, "Mosconi y Gatica"],
      ["RIVAS299", -38.959302, -68.079020, "Mosconi y Rivas"],
      ["NV1194", -38.950315, -68.175466, "San Martín y Gatica"],
      ["NV1195", -38.946710, -68.180058, "San Martín y Saavedra"],
      ["NV1201", -38.949172, -68.187418, "San Martín y Bejarano"],
      ["NV1202", -38.947912, -68.187633, "San Martín y Solalique"],
      ["NV1204", -38.946477, -68.187665, "San Martín y Crouzeilles"],
      ["NV1205", -38.944908, -68.187633, "San Martín / Aeropuerto Norte"],
      ["NV1160", -38.944516, -68.215055, "Belgrano y Constituyentes"],
      ["NV1150", -38.944657, -68.197331, "San Martín y Futaleufú"],
      ["NV1244", -38.930301, -68.252027, "Barrio 108 Viviendas"],
      ["NV1259", -38.953457, -68.237667, "Constituyentes y Perito Moreno"],
      ["NV2000", -38.960410, -68.246800, "Cabecera Plottier (50B)"]
    ];

    let map;
    let capaRuta = null;
    let capaParadas = null;
    let marcadoresBuses = {};
    let mostrandoParadas = true;
    let cooldownTimer = null;

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.16], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap'
      }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      dibujarParadasEnMapa();
    }

    function dibujarParadasEnMapa() {
      capaParadas.clearLayers();

      TODAS_LAS_PARADAS.forEach(p => {
        const id = p[0];
        const lat = p[1];
        const lon = p[2];
        const desc = p[3] || "Parada oficial";

        const marker = L.circleMarker([lat, lon], {
          radius: 5,
          color: '#FAB387',
          fillColor: '#F9E2AF',
          fillOpacity: 0.9,
          weight: 1.5
        });

        const popupContent = `
          <div style="min-width: 175px; font-family: sans-serif;">
            <div class="stop-popup-title">📍 Parada ${id}</div>
            <div class="stop-popup-desc">${desc}</div>
            <div style="margin-bottom: 6px;">
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1013', '50A')">⏱️ Ver 50A</button>
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1014', '50B')">⏱️ Ver 50B</button>
            </div>
            <div id="res-${id}" class="result-box" style="display:none;"></div>
          </div>
        `;

        marker.bindPopup(popupContent);
        capaParadas.addLayer(marker);
      });
    }

    async function consultarArriboEnParada(idParada, codLinea, linea) {
      const resBox = document.getElementById(`res-${idParada}`);
      if (!resBox) return;

      resBox.style.display = 'block';
      resBox.innerHTML = `<em>Consultando arribo para Línea ${linea}...</em>`;

      try {
        const r = await fetch(`/api/consulta_parada?parada=${idParada}&cod=${codLinea}&linea=${linea}`);
        const data = await r.json();

        if (!data.arribos || data.arribos.length === 0) {
          resBox.innerHTML = `Sin arribos próximos de Línea ${linea}.`;
        } else {
          let html = '';
          data.arribos.forEach(a => {
            html += `<div><strong>Línea ${linea}</strong>: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span><br><small style="color:#666;">${a.ramal}</small></div>`;
          });
          resBox.innerHTML = html;
        }
      } catch (err) {
        resBox.innerHTML = `Error al consultar la parada.`;
      }
    }

    function toggleParadas() {
      const btn = document.getElementById('btn-toggle-stops');
      if (mostrandoParadas) {
        map.removeLayer(capaParadas);
        btn.innerText = "📍 Ver Paradas";
        mostrandoParadas = false;
      } else {
        map.addLayer(capaParadas);
        btn.innerText = "📍 Ocultar Paradas";
        mostrandoParadas = true;
      }
    }

    function limpiarRuta() {
      capaRuta.clearLayers();
      document.getElementById('btn-clear').style.display = 'none';
    }

    function centrarEn(lat, lon) {
      if (!lat || !lon) return;
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
        iniciarCooldown(5);
      } catch (err) {
        status.innerText = "Reintentando sincronización...";
      }
    }

    function actualizarMapa(buses) {
      const countLabel = document.getElementById('bus-count');
      if (!buses || buses.length === 0) {
        countLabel.innerText = "Sin unidades reportando con GPS";
        return;
      }

      const activos = buses.filter(b => b.estado === 'activo').length;
      const perdidos = buses.filter(b => b.estado === 'perdido').length;
      countLabel.innerText = `🚌 ${activos} en camino (GPS)${perdidos > 0 ? ' | ⚠️ ' + perdidos + ' señal débil' : ''}`;

      const idsRecibidos = new Set();

      buses.forEach(b => {
        if (!b.lat || !b.lon || isNaN(b.lat) || isNaN(b.lon)) return;

        idsRecibidos.add(b.id);
        const esPerdido = (b.estado === 'perdido');
        
        const claseCss = (b.linea === "50A") ? "bus-marker-50a" : "bus-marker-50b";
        const iconoHtml = `<div class="bus-marker ${claseCss} ${esPerdido ? 'bus-marker-lost' : ''}">${esPerdido ? '⚠️' : '🚌'} ${b.linea}</div>`;
        const icon = L.divIcon({
          className: 'custom-icon',
          html: iconoHtml,
          iconSize: [58, 24],
          iconAnchor: [29, 12]
        });

        const sentidoTexto = (b.sentido_code === 'HACIA_NEUQUEN') ? '🟠 Hacia Neuquén' : '🟢 Hacia Plottier';
        const estadoColor = esPerdido ? '#e74c3c' : (b.sentido_code === 'HACIA_NEUQUEN' ? '#FAB387' : '#A6E3A1');
        const tiempoTexto = b.tiempo_cabecera 
          ? `<div style="color: #27ae60; font-weight: bold; margin-top: 5px;">⏱️ Arribo cabecera: ${b.tiempo_cabecera}</div>` 
          : `<div style="color: #7f8c8d; font-style: italic; margin-top: 5px;">📍 En trayecto</div>`;

        const contenidoPopup = `
          <div style="font-family: sans-serif; font-size: 13px; line-height: 1.4; min-width: 170px;">
            <strong style="color: #111; font-size: 14px;">Línea ${b.linea}</strong><br>
            <span style="color: ${estadoColor}; font-weight: 700;">${sentidoTexto}</span><br>
            <span style="color: #555; font-size: 12px;">Ramal: ${b.ramal}</span>
            ${tiempoTexto}
          </div>
        `;

        if (marcadoresBuses[b.id]) {
          marcadoresBuses[b.id].setLatLng([b.lat, b.lon]);
          marcadoresBuses[b.id].setIcon(icon);
          marcadoresBuses[b.id].getPopup().setContent(contenidoPopup);
        } else {
          const marker = L.marker([b.lat, b.lon], { icon: icon });
          marker.bindPopup(contenidoPopup);
          marker.addTo(map);
          marcadoresBuses[b.id] = marker;
        }
      });

      for (let id in marcadoresBuses) {
        if (!idsRecibidos.has(id)) {
          map.removeLayer(marcadoresBuses[id]);
          delete marcadoresBuses[id];
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

        const tagClase = (item.linea === "50A") ? "line-50a" : "line-50b";

        html += `<div class="card">
          <div class="card-header">
            <span class="line-tag ${tagClase}">Línea ${item.linea}</span>
            <span class="stop-tag">Cabecera ${item.parada}</span>
          </div>`;

        if (!item.arribos || item.arribos.length === 0) {
          html += `<div class="empty">Sin unidades reportando en este momento</div>`;
        } else {
          item.arribos.forEach(c => {
            const tieneGps = (c.lat && c.lon && Math.abs(c.lat) > 1);
            const botonVer = tieneGps 
              ? `<button class="btn-action" onclick="centrarEn(${c.lat}, ${c.lon})">Ver en Mapa</button>` 
              : '';

            const badgeClass = (c.sentido_code === 'HACIA_NEUQUEN') ? 'badge-neuquen' : 'badge-plottier';
            const badgeIcon = (c.sentido_code === 'HACIA_NEUQUEN') ? '🟠' : '🟢';

            html += `<div class="arrival-row">
              <div>
                <div class="branch-row">
                  <span class="branch">${c.ramal}</span>
                  <span class="badge-status ${badgeClass}">${badgeIcon} ${c.sentido}</span>
                </div>
                <div class="time-label">Próximo arribo: <span class="time-val">${c.tiempo}</span></div>
                ${!tieneGps ? '<div class="no-gps-hint">⏳ Salida programada (sin GPS activo)</div>' : ''}
              </div>
              <div>${botonVer}</div>
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

# Endpoint on-demand para consultar cualquier parada del mapa al tocarla
@app.route('/api/consulta_parada')
def api_consulta_parada():
    global flota_memoria
    parada = request.args.get('parada')
    cod = request.args.get('cod', '1013')
    linea = request.args.get('linea', '50A')
    ahora = time.time()

    if not parada:
        return jsonify({"arribos": []}), 400

    arribos_raw = consultar_arribos(parada, cod)
    arribos_limpios = []

    for c in arribos_raw:
        lat = c.get("latitud")
        lon = c.get("longitud")
        tiempo = c.get("tiempoRestanteArribo", "Sin datos")
        ramal = c.get("descripcionBandera", linea)

        ramal_upper = str(ramal).upper()
        if "VUELTA" in ramal_upper:
            sentido = "Hacia Plottier"
            sentido_code = "HACIA_PLOTTIER"
        elif "IDA" in ramal_upper:
            sentido = "Hacia Neuquén"
            sentido_code = "HACIA_NEUQUEN"
        else:
            sentido = "Hacia Neuquén"
            sentido_code = "HACIA_NEUQUEN"

        f_lat, f_lon = None, None
        if lat and lon and str(lat).strip() and str(lon).strip():
            try:
                f_lat = float(str(lat).replace(',', '.').strip())
                f_lon = float(str(lon).replace(',', '.').strip())
                if abs(f_lat) < 1 or abs(f_lon) < 1:
                    f_lat, f_lon = None, None
            except ValueError:
                pass

        arribos_limpios.append({
            "tiempo": tiempo,
            "ramal": ramal,
            "sentido": sentido,
            "sentido_code": sentido_code,
            "lat": f_lat,
            "lon": f_lon
        })

        # Alimentar el mapa en vivo si la parada encontró un coche con GPS
        if f_lat and f_lon:
            nuevo_id = f"{linea}_{sentido_code}_{round(f_lat, 3)}_{round(f_lon, 3)}"
            flota_memoria[nuevo_id] = {
                "id": nuevo_id,
                "linea": linea,
                "ramal": ramal,
                "sentido": sentido,
                "sentido_code": sentido_code,
                "tiempo_cabecera": tiempo,
                "lat": f_lat,
                "lon": f_lon,
                "last_seen": ahora
            }

    return jsonify({"parada": parada, "linea": linea, "arribos": arribos_limpios})

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
    buses_leidos_ronda = []

    for item in CONSULTAS_CABECERA:
        arribos_raw = consultar_arribos(item["parada"], item["cod"])
        arribos_limpios = []
        es_cabecera = (item["seccion"] == "CABECERA")

        for c in arribos_raw:
            lat = c.get("latitud")
            lon = c.get("longitud")
            tiempo = c.get("tiempoRestanteArribo", "Sin datos")
            ramal = c.get("descripcionBandera", item["linea"])

            ramal_upper = str(ramal).upper()
            if "VUELTA" in ramal_upper:
                sentido = "Hacia Plottier"
                sentido_code = "HACIA_PLOTTIER"
            elif "IDA" in ramal_upper:
                sentido = "Hacia Neuquén"
                sentido_code = "HACIA_NEUQUEN"
            else:
                sentido = "Hacia Neuquén" if es_cabecera else "Hacia Plottier"
                sentido_code = "HACIA_NEUQUEN" if es_cabecera else "HACIA_PLOTTIER"

            f_lat, f_lon = None, None
            if lat and lon and str(lat).strip() and str(lon).strip():
                try:
                    f_lat = float(str(lat).replace(',', '.').strip())
                    f_lon = float(str(lon).replace(',', '.').strip())
                    if abs(f_lat) < 1 or abs(f_lon) < 1:
                        f_lat, f_lon = None, None
                except ValueError:
                    pass

            if item["mostrar"]:
                arribos_limpios.append({
                    "tiempo": tiempo,
                    "ramal": ramal,
                    "sentido": sentido,
                    "sentido_code": sentido_code,
                    "lat": f_lat,
                    "lon": f_lon
                })

            if f_lat and f_lon:
                buses_leidos_ronda.append({
                    "linea": item["linea"],
                    "ramal": ramal,
                    "sentido": sentido,
                    "sentido_code": sentido_code,
                    "tiempo": tiempo,
                    "es_cabecera": es_cabecera,
                    "lat": f_lat,
                    "lon": f_lon
                })

        if item["mostrar"]:
            nuevas_cabeceras.append({**item, "arribos": arribos_limpios})

        consultas_ok += 1
        time.sleep(0.3)

    # Deduplicación estricta intra-ronda a 45m
    buses_unicos_ronda = []
    for b in buses_leidos_ronda:
        es_duplicado = False
        for u in buses_unicos_ronda:
            if u["linea"] == b["linea"] and u["sentido_code"] == b["sentido_code"]:
                if calcular_distancia(u["lat"], u["lon"], b["lat"], b["lon"]) < 0.045:
                    es_duplicado = True
                    if b["es_cabecera"] and not u["es_cabecera"]:
                        u["tiempo"] = b["tiempo"]
                        u["es_cabecera"] = True
                    break
        if not es_duplicado:
            buses_unicos_ronda.append(b)

    # Seguimiento de flota inter-ciclo
    for b in buses_unicos_ronda:
        bus_match_id = None
        menor_distancia = 0.90

        for bus_id, datos in flota_memoria.items():
            if datos["linea"] == b["linea"] and datos["sentido_code"] == b["sentido_code"]:
                dist = calcular_distancia(datos["lat"], datos["lon"], b["lat"], b["lon"])
                if dist < menor_distancia:
                    menor_distancia = dist
                    bus_match_id = bus_id

        if bus_match_id:
            flota_memoria[bus_match_id]["lat"] = b["lat"]
            flota_memoria[bus_match_id]["lon"] = b["lon"]
            flota_memoria[bus_match_id]["last_seen"] = ahora
            flota_memoria[bus_match_id]["ramal"] = b["ramal"]
            flota_memoria[bus_match_id]["sentido"] = b["sentido"]
            flota_memoria[bus_match_id]["sentido_code"] = b["sentido_code"]
            if b["es_cabecera"]:
                flota_memoria[bus_match_id]["tiempo_cabecera"] = b["tiempo"]
        else:
            nuevo_id = f"{b['linea']}_{b['sentido_code']}_{round(b['lat'], 3)}_{round(b['lon'], 3)}"
            flota_memoria[nuevo_id] = {
                "id": nuevo_id,
                "linea": b["linea"],
                "ramal": b["ramal"],
                "sentido": b["sentido"],
                "sentido_code": b["sentido_code"],
                "tiempo_cabecera": b["tiempo"] if b["es_cabecera"] else None,
                "lat": b["lat"],
                "lon": b["lon"],
                "last_seen": ahora
            }

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
            "sentido_code": datos["sentido_code"],
            "tiempo_cabecera": datos["tiempo_cabecera"],
            "lat": datos["lat"],
            "lon": datos["lon"],
            "estado": estado
        })
    return lista

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
