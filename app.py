import os
import re
import time
import json
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# Configuración de zona horaria Argentina UTC-3
TZ_AR = timezone(timedelta(hours=-3))

URL_BASE = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = "https://cuandollega.smartmovepro.net/indalo/recorridos?handler=Arribos"

# Paradas clave para rotación en segundo plano (1 cada 3.5s)
COLA_PARADAS = [
    # 50A
    {"linea": "50A", "cod": "1013", "parada": "NV1244", "cabecera": True},
    {"linea": "50A", "cod": "1013", "parada": "NV1014", "cabecera": True},

    # 50B
    {"linea": "50B", "cod": "1014", "parada": "NV2000", "cabecera": True},
    {"linea": "50B", "cod": "1014", "parada": "NV4000", "cabecera": True},

    # 50R
    {"linea": "50R", "cod": "1015", "parada": "NV5028", "cabecera": True},
    {"linea": "50R", "cod": "1015", "parada": "NV5000", "cabecera": True},

    # URBANO
    {"linea": "URBANO", "cod": "1016", "parada": "NV1259", "cabecera": True},
    {"linea": "URBANO", "cod": "1016", "parada": "NV1032", "cabecera": True}
]

ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": [],
    "cabeceras": [],
    "total_buses": 0,
    "servicio_activo": True
}

# Carga de trazas y paradas desde el JSON de IndexedDB si existe en el repo
RUTAS_GEO = {"50A": {}, "50B": {}, "50R": {}, "URBANO": {}}
TODAS_LAS_PARADAS = []

def cargar_recorridos_locales():
    global RUTAS_GEO, TODAS_LAS_PARADAS
    posibles_archivos = ["recorridos.json", "urbano y r.json", "smartmove_indexeddb_dump.json"]
    archivo_encontrado = None

    for f in posibles_archivos:
        ruta = os.path.join(os.path.dirname(__file__), f)
        if os.path.exists(ruta):
            archivo_encontrado = ruta
            break

    if not archivo_encontrado:
        return

    try:
        with open(archivo_encontrado, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)

        recorridos = data.get("DBCuandoLlega", {}).get("recorridos", [])
        mapa_lineas = {"1013": "50A", "1014": "50B", "1015": "50R", "1016": "URBANO"}
        paradas_dict = {}

        for rec in recorridos:
            cod = str(rec.get("codigoLinea"))
            linea_nom = mapa_lineas.get(cod)
            if not linea_nom:
                continue

            bandera = str(rec.get("bandera", "")).upper()
            sentido = "HACIA_PLOTTIER" if "IDA" in bandera else "HACIA_NEUQUEN"

            puntos = [
                [round(p["latitud"], 6), round(p["longitud"], 6)]
                for p in rec.get("puntos", [])
                if p.get("latitud") and p.get("longitud")
            ]
            RUTAS_GEO[linea_nom][sentido] = puntos

            for p in rec.get("paradas", []):
                p_id = str(p.get("identificador") or "").strip()
                lat = p.get("latitudParada")
                lon = p.get("longitudParada")
                if p_id and lat and lon and p_id not in paradas_dict:
                    try:
                        paradas_dict[p_id] = [
                            p_id,
                            round(float(str(lat).replace(',', '.')), 6),
                            round(float(str(lon).replace(',', '.')), 6),
                            p.get("descripcion") or p_id
                        ]
                    except ValueError:
                        continue

        TODAS_LAS_PARADAS = list(paradas_dict.values())
    except Exception as e:
        print(f"Error cargando JSON de recorridos: {e}")

cargar_recorridos_locales()

def esta_en_horario_servicio():
    ahora = datetime.now(TZ_AR)
    minutos = ahora.hour * 60 + ahora.minute
    return (5 * 60 + 30) <= minutos or minutos <= (0 * 60 + 30)

def recolector_segundo_plano():
    global ESTADO_GLOBAL
    buses_cache = {}
    cabeceras_cache = {}

    session = requests.Session()
    headers_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://cuandollega.smartmovepro.net",
        "Referer": URL_BASE,
        "X-Requested-With": "XMLHttpRequest"
    }

    token = None

    while True:
        if not esta_en_horario_servicio():
            ESTADO_GLOBAL["servicio_activo"] = False
            time.sleep(60)
            continue

        ESTADO_GLOBAL["servicio_activo"] = True

        if not token:
            try:
                r_init = session.get(URL_BASE, headers={"User-Agent": headers_base["User-Agent"]}, timeout=10)
                m = re.search(r'CfDJ8[A-Za-z0-9_\-]{80,}', r_init.text) or re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', r_init.text)
                token = m.group(1) if m and m.groups() else (m.group(0) if m else None)
            except Exception:
                time.sleep(5)
                continue

        for item in COLA_PARADAS:
            try:
                headers = {**headers_base, "RequestVerificationToken": token}
                payload = {"IdentificadorParada": item["parada"], "CodigoLinea": item["cod"]}

                res = session.post(URL_API, json=payload, headers=headers, timeout=8)

                if res.status_code == 429:
                    time.sleep(6)
                    continue

                if res.status_code == 200:
                    data = res.json()
                    arribos = data.get("arribos", [])

                    if item["cabecera"] and arribos:
                        cabeceras_cache[f"{item['linea']}_{item['parada']}"] = {
                            "linea": item["linea"],
                            "parada": item["parada"],
                            "arribos": [
                                {
                                    "ramal": a.get("descripcionBandera"),
                                    "tiempo": a.get("tiempoRestanteArribo"),
                                    "sentido": "Hacia Neuquén" if "VUELTA" in str(a.get("descripcionBandera", "")).upper() else "Hacia Plottier",
                                    "sentido_code": "HACIA_NEUQUEN" if "VUELTA" in str(a.get("descripcionBandera", "")).upper() else "HACIA_PLOTTIER",
                                    "lat": float(str(a["latitud"]).replace(',', '.')) if a.get("latitud") else None,
                                    "lon": float(str(a["longitud"]).replace(',', '.')) if a.get("longitud") else None
                                } for a in arribos
                            ]
                        }

                    for a in arribos:
                        if not a.get("latitud") or not a.get("longitud"):
                            continue

                        lat = float(str(a["latitud"]).replace(',', '.'))
                        lon = float(str(a["longitud"]).replace(',', '.'))
                        bandera = str(a.get("descripcionBandera", "")).upper()
                        sentido = "Hacia Neuquén" if "VUELTA" in bandera else "Hacia Plottier"
                        sentido_code = "HACIA_NEUQUEN" if "VUELTA" in bandera else "HACIA_PLOTTIER"

                        # ID estable agrupado por proximidad para movimiento suave
                        id_bus = f"{item['linea']}_{sentido_code}_{round(lat, 2)}_{round(lon, 2)}"

                        buses_cache[id_bus] = {
                            "id": id_bus,
                            "linea": item["linea"],
                            "ramal": a.get("descripcionBandera"),
                            "sentido": sentido,
                            "sentido_code": sentido_code,
                            "tiempo_arribo": a.get("tiempoRestanteArribo"),
                            "lat": lat,
                            "lon": lon,
                            "ultimo_reporte": time.time()
                        }
            except Exception:
                token = None

            time.sleep(3.5)

        # Eliminar unidades sin reporte por más de 4 minutos
        ahora_ts = time.time()
        buses_cache = {k: v for k, v in buses_cache.items() if ahora_ts - v["ultimo_reporte"] < 240}

        ESTADO_GLOBAL = {
            "timestamp": datetime.now(TZ_AR).strftime("%H:%M:%S"),
            "cabeceras": list(cabeceras_cache.values()),
            "buses": list(buses_cache.values()),
            "total_buses": len(buses_cache),
            "servicio_activo": True
        }

hilo_poller = Thread(target=recolector_segundo_plano, daemon=True)
hilo_poller.start()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-CE85R9NET5"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-CE85R9NET5');
  </script>

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - En Vivo</title>
  
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
    #map { height: 380px; width: 100%; background: #11111B; }
    
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.9); backdrop-filter: blur(6px); padding: 5px 12px; border-radius: 8px; font-size: 11px; color: #CDD6F4; border: 1px solid #313244; font-weight: 600; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.9); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }

    .section-title { font-size: 14px; color: #F5E0DC; text-transform: uppercase; letter-spacing: 1px; margin: 14px 0 8px; font-weight: 700; }
    .card { background: #1E1E2E; border: 1px solid #313244; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .line-tag { background: #313244; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: 6px; }
    .line-50a { color: #A6E3A1; }
    .line-50b { color: #89B4FA; }
    .line-50r { color: #CBA6F7; }
    .line-urbano { color: #F9E2AF; }
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

    /* Animación fluida de posición estilo Uber */
    .leaflet-marker-icon { transition: transform 1.5s cubic-bezier(0.25, 1, 0.5, 1); cursor: pointer; }
    .bus-marker { display: flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.6); }
    .bus-marker-50a { background-color: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background-color: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background-color: #2F1E3A; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background-color: #3A321E; border: 2px solid #F9E2AF; color: #F9E2AF; }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; margin-bottom: 2px; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 8px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 5px 9px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin-right: 4px; margin-top: 4px; }
    .result-box { margin-top: 8px; padding-top: 6px; border-top: 1px solid #ddd; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS y paradas en tiempo real (50A, 50B, 50R y Urbano)</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRuta()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
    <div id="map"></div>
  </div>

  <div class="section-title">📍 Cabeceras Principales</div>
  <div id="contenido">Cargando datos de arribo...</div>

  <div class="credits">
    Desarrollado por <span class="author">Ramiro Alzogaray</span>
    <span class="alias-badge">App en desarrollo, puede contener fallos</span>
  </div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-box">
      <div id="status" class="status-text">Iniciando...</div>
      <div id="hint" class="cached-hint">Conexión interna activa</div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <script>
    const ENDPOINT_LOCAL = "/api/arribos";

    // Inyectado directamente por Flask desde la base de datos de SmartMovePro
    const RUTAS_GEO = {{ rutas_geo|safe }};
    const TODAS_LAS_PARADAS = {{ paradas|safe }};

    let map;
    let capaRuta = null;
    let capaParadas = null;
    let marcadoresBuses = {};
    let mostrandoParadas = true;
    let cooldownTimer = null;

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.20], 12);
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
          radius: 4.5,
          color: '#FAB387',
          fillColor: '#F9E2AF',
          fillOpacity: 0.85,
          weight: 1.5
        });

        const popupContent = `
          <div style="min-width: 175px; font-family: sans-serif;">
            <div class="stop-popup-title">📍 Parada ${id}</div>
            <div class="stop-popup-desc">${desc}</div>
            <div style="margin-bottom: 6px;">
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1013', '50A')">50A</button>
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1014', '50B')">50B</button>
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1015', '50R')">50R</button>
              <button class="btn-query-stop" onclick="consultarArriboEnParada('${id}', '1016', 'URB')">Urb</button>
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
        const r = await fetch(`/api/parada?id=${idParada}&cod=${codLinea}&linea=${linea}`);
        const data = await r.json();

        if (!data.arribos || data.arribos.length === 0) {
          resBox.innerHTML = `Sin arribos próximos de Línea ${linea}.`;
        } else {
          let html = '';
          data.arribos.forEach(a => {
            const color = a.sentido_code === 'HACIA_PLOTTIER' ? '#2ecc71' : '#e67e22';
            html += `<div style="margin-bottom:4px;">
              <strong>Línea ${linea}</strong> (${a.ramal})<br>
              <span style="color:${color}; font-weight:700;">${a.sentido}</span><br>
              Arribo: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span>
            </div>`;
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

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      const l = linea.toUpperCase();
      if (!RUTAS_GEO[l]) return;

      const sentidoActivo = sentidoCode || "HACIA_NEUQUEN";
      const sentidoSecundario = (sentidoActivo === "HACIA_NEUQUEN") ? "HACIA_PLOTTIER" : "HACIA_NEUQUEN";

      let colorBase = "#89B4FA";
      let colorSec = "#1D4ED8";

      if (l === "50A") { colorBase = "#A6E3A1"; colorSec = "#16A085"; }
      else if (l === "50R") { colorBase = "#CBA6F7"; colorSec = "#8839EF"; }
      else if (l.includes("URB")) { colorBase = "#F9E2AF"; colorSec = "#DF8E1D"; }

      if (RUTAS_GEO[l][sentidoSecundario] && RUTAS_GEO[l][sentidoSecundario].length > 0) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[l][sentidoSecundario], { color: colorSec, weight: 3.5, opacity: 0.55, lineJoin: 'round' }));
      }
      if (RUTAS_GEO[l][sentidoActivo] && RUTAS_GEO[l][sentidoActivo].length > 0) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[l][sentidoActivo], { color: colorBase, weight: 6, opacity: 0.95, lineJoin: 'round' }));
      }
      document.getElementById('btn-clear').style.display = 'block';
    }

    function limpiarRuta() {
      capaRuta.clearLayers();
      document.getElementById('btn-clear').style.display = 'none';
    }

    function centrarEn(lat, lon, linea, sentidoCode) {
      if (!lat || !lon) return;
      map.setView([lat, lon], 15, { animate: true });
      mostrarRuta(linea, sentidoCode);
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
        const res = await fetch(ENDPOINT_LOCAL);
        const data = await res.json();
        
        if (!data) throw new Error("Sin respuesta del servidor");

        renderTarjetas(data.cabeceras);
        actualizarMapa(data.buses);

        status.innerText = "Actualizado: " + data.timestamp;
        iniciarCooldown(3);
      } catch (err) {
        status.innerText = "Sincronizando con el servidor...";
      }
    }

    function actualizarMapa(buses) {
      const countLabel = document.getElementById('bus-count');
      if (!buses || buses.length === 0) {
        countLabel.innerText = "Sin unidades reportando en este momento";
        return;
      }

      countLabel.innerText = `🚌 ${buses.length} colectivos en vivo`;
      const idsRecibidos = new Set();

      buses.forEach(b => {
        if (!b.lat || !b.lon || isNaN(b.lat) || isNaN(b.lon)) return;

        idsRecibidos.add(b.id);
        const lUpper = (b.linea || "").toUpperCase();

        let claseCss = "bus-marker-50b";
        if (lUpper === "50A") claseCss = "bus-marker-50a";
        else if (lUpper === "50R") claseCss = "bus-marker-50r";
        else if (lUpper.includes("URB")) claseCss = "bus-marker-urbano";

        const iconoHtml = `<div class="bus-marker ${claseCss}">🚌 ${b.linea}</div>`;
        const icon = L.divIcon({ className: 'custom-icon', html: iconoHtml, iconSize: [60, 24], iconAnchor: [30, 12] });

        const sentidoTexto = (b.sentido_code === 'HACIA_NEUQUEN') ? '🟠 Hacia Neuquén' : '🟢 Hacia Plottier';
        const estadoColor = (b.sentido_code === 'HACIA_NEUQUEN') ? '#FAB387' : '#A6E3A1';
        const tiempoTexto = b.tiempo_arribo 
          ? `<div style="color: #27ae60; font-weight: bold; margin-top: 5px;">⏱️ Próximo arribo: ${b.tiempo_arribo}</div>` 
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
          marker.on('click', () => { mostrarRuta(b.linea, b.sentido_code); });
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

    function renderTarjetas(cabeceras) {
      if (!cabeceras || cabeceras.length === 0) return;
      let html = '';

      cabeceras.forEach(cabe => {
        const lUpper = (cabe.linea || "").toUpperCase();
        let tagClase = "line-50b";
        if (lUpper === "50A") tagClase = "line-50a";
        else if (lUpper === "50R") tagClase = "line-50r";
        else if (lUpper.includes("URB")) tagClase = "line-urbano";

        html += `<div class="card">
          <div class="card-header">
            <span class="line-tag ${tagClase}">Línea ${cabe.linea}</span>
            <span class="stop-tag">Cabecera ${cabe.parada}</span>
          </div>`;

        if (!cabe.arribos || cabe.arribos.length === 0) {
          html += `<div class="empty">Sin unidades reportando hacia cabecera</div>`;
        } else {
          cabe.arribos.forEach(c => {
            const tieneGps = (c.lat && c.lon && Math.abs(c.lat) > 1);
            const badgeClass = (c.sentido_code === 'HACIA_NEUQUEN') ? 'badge-neuquen' : 'badge-plottier';
            const badgeIcon = (c.sentido_code === 'HACIA_NEUQUEN') ? '🟠' : '🟢';

            const botonVer = tieneGps 
              ? `<button class="btn-action" onclick="centrarEn(${c.lat}, ${c.lon}, '${cabe.linea}', '${c.sentido_code}')">Ver en Mapa</button>` 
              : '';

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
    setInterval(pedirDatos, 12000);
  </script>
</body>
</html>
"""

@app.route('/ping')
def ping():
    return "OK", 200

@app.route('/')
def home():
    return render_template_string(
        HTML_TEMPLATE,
        rutas_geo=json.dumps(RUTAS_GEO),
        paradas=json.dumps(TODAS_LAS_PARADAS)
    )

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
    return jsonify(ESTADO_GLOBAL), 200

@app.route('/api/parada')
def api_parada():
    p_id = request.args.get("id")
    p_cod = request.args.get("cod", "1013")
    p_linea = request.args.get("linea", "50A")

    if not p_id:
        return jsonify({"arribos": []}), 200

    try:
        s = requests.Session()
        r_init = s.get(URL_BASE, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        m = re.search(r'CfDJ8[A-Za-z0-9_\-]{80,}', r_init.text) or re.search(r'__RequestVerificationToken.*?value=["\']([^"\']+)["\']', r_init.text)
        token = m.group(1) if m and m.groups() else (m.group(0) if m else None)

        res = s.post(URL_API, json={"IdentificadorParada": p_id, "CodigoLinea": p_cod}, headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://cuandollega.smartmovepro.net",
            "Referer": URL_BASE,
            "RequestVerificationToken": token,
            "X-Requested-With": "XMLHttpRequest"
        }, timeout=6)

        if res.status_code == 200:
            data = res.json()
            arribos = [
                {
                    "ramal": a.get("descripcionBandera"),
                    "tiempo": a.get("tiempoRestanteArribo"),
                    "sentido": "Hacia Neuquén" if "VUELTA" in str(a.get("descripcionBandera", "")).upper() else "Hacia Plottier",
                    "sentido_code": "HACIA_NEUQUEN" if "VUELTA" in str(a.get("descripcionBandera", "")).upper() else "HACIA_PLOTTIER"
                } for a in data.get("arribos", [])
            ]
            return jsonify({"parada": p_id, "linea": p_linea, "arribos": arribos}), 200
    except Exception:
        pass

    return jsonify({"parada": p_id, "linea": p_linea, "arribos": []}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
