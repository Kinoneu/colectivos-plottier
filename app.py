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

# Cargar paradas y trazas con rutas seguras
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
    "fuente": "Iniciando..."
}

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
    while True:
        session, token = obtener_sesion_smp()
        exito_directo = False

        if session and token:
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
                        procesar_arribos_en_radar(res.json().get("arribos", []), item["linea"], item["parada"])
                    elif res.status_code == 429:
                        time.sleep(10)
                except Exception:
                    break
                time.sleep(3.5)

        if not exito_directo:
            try:
                r_work = requests.get(URL_WORKER, timeout=10)
                if r_work.status_code == 200:
                    for b in r_work.json().get("buses", []):
                        procesar_arribos_en_radar([b], b.get("linea"), b.get("parada_detectada", "Worker"))
                    ESTADO_GLOBAL["fuente"] = "Red Colaborativa"
            except Exception:
                pass
        else:
            ESTADO_GLOBAL["fuente"] = "En Vivo"

        ahora = time.time()
        ESTADO_GLOBAL["buses"] = {k: v for k, v in ESTADO_GLOBAL["buses"].items() if ahora - v["updated_at"] < 210}

        try:
            ESTADO_GLOBAL["timestamp"] = datetime.now(zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")
            
        time.sleep(15)

Thread(target=recolector_segundo_plano, daemon=True).start()

@app.route('/api/parada')
def api_parada():
    p_id = request.args.get("id")
    p_cod = request.args.get("cod")
    p_linea = request.args.get("linea")
    if not p_id or not p_cod:
        return jsonify({"arribos": []})

    try:
        r = requests.get(f"{URL_WORKER}parada?id={p_id}&cod={p_cod}&linea={p_linea}", timeout=8)
        if r.status_code == 200:
            data = r.json()
            procesar_arribos_en_radar([
                {**a, "linea": p_linea, "tiempo_arribo": a.get("tiempo")}
                for a in data.get("arribos", []) if a.get("lat") and a.get("lon")
            ], p_linea, p_id)
            return jsonify(data)
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
    return jsonify({"trazas": TRAZAS_GEO, "paradas": PARADAS_DATA})

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
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 105px; display: flex; flex-direction: column; min-height: 100vh;}
    header { margin-bottom: 12px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 2px;}
    .sub { font-size: 13px; color: #A6ADC8; }
    .author-badge { font-size: 12px; color: #A6E3A1; font-weight: 700; display: inline-block; padding-top: 4px; }
    
    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; box-shadow: 0 6px 15px rgba(0,0,0,0.4);}
    #map { height: 480px; width: 100%; background: #11111B; }
    
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.9); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #CDD6F4; border: 1px solid #313244; font-weight: 700; box-shadow: 0 4px 6px rgba(0,0,0,0.3);}
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.95); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 7px 12px; border-radius: 8px; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: all 0.2s;}
    .btn-map-control:active { transform: scale(0.95); }

    /* Marcador Uber Style sin CSS transition para no bugear el zoom */
    .bus-marker { display: flex; align-items: center; justify-content: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 3px 8px rgba(0,0,0,0.7); }
    .bus-marker-50a { background: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background: #38243E; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background: #3E3724; border: 2px solid #F9E2AF; color: #F9E2AF; }
    
    /* Estados del colectivo */
    .bus-warning { border-color: #FAB387; color: #FAB387; }
    .bus-danger { border-color: #F38BA8; color: #F38BA8; }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-bottom: 6px;}
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 8px; }
    .btn-query-stop { background: #181825; color: #CDD6F4; border: 1px solid #45475A; padding: 6px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px 2px 0 0; width: 100%; transition: background 0.2s;}
    .btn-query-stop:active { background: #313244; }
    .result-box { margin-top: 8px; padding-top: 6px; border-top: 1px solid #eee; font-size: 12px; color: #111; }

    .beta-notice { text-align: center; font-size: 11px; color: #6C7086; margin-top: auto; padding: 16px 10px 0; font-style: italic; line-height: 1.4; }

    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.98); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; box-shadow: 0 -4px 15px rgba(0,0,0,0.5);}
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 14px; font-weight: 800; padding: 12px 20px; border-radius: 10px; cursor: pointer; transition: opacity 0.2s;}
    .btn-refresh:active { opacity: 0.8; }
    .status-box { text-align: right; }
    .status-text { font-size: 12px; color: #A6ADC8; font-weight: 600;}
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS Predictivo en Vivo (50A, 50B, 50R y Urbano)</p>
    <span class="author-badge">Desarrollado por Ramiro Alzogaray</span>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Iniciando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRutas()" style="display:none;">✕ Quitar Ruta</button>
    </div>
    <div id="map"></div>
  </div>

  <div class="beta-notice">
    * Esta app está en desarrollo y la misma es una versión beta, puede contener errores de sincronización con Indalo.
  </div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatosForzado()">Actualizar</button>
    <div class="status-box">
      <div class="status-text" id="status">Sincronizando...</div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map, capaRuta, capaParadas;
    let RUTAS_GEO = {};
    let mostrandoParadas = true;
    
    // Estado del motor de predicción
    let stateBuses = {}; 
    let animators = {};

    async function init() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.18], 13);
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      try {
        const r = await fetch('/api/static_data');
        const data = await r.json();
        RUTAS_GEO = data.trazas;
        dibujarParadas(data.paradas);
      } catch(e) {}

      pedirDatos();
      setInterval(pedirDatos, 8000); // Polling rápido para alimentar el motor de predicción
    }

    function dibujarParadas(paradas) {
      capaParadas.clearLayers();
      paradas.forEach(p => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        let botones = '';
        for (const [linNom, info] of Object.entries(lineas)) {
          botones += `<button class="btn-query-stop" onclick="consultarParada('${id}', '${info.parada}', '${info.cod}', '${linNom}')">⏱️ Consultar ${linNom}</button>`;
        }

        const marker = L.circleMarker([lat, lon], {
          radius: 5, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.9, weight: 2
        });

        marker.bindPopup(`
          <div style="min-width:160px;">
            <div class="stop-popup-title">${desc}</div>
            <div class="stop-popup-desc">Ref: ${id}</div>
            <div>${botones}</div>
            <div id="res-${id.replace(/[^a-zA-Z0-9]/g, '')}" class="result-box" style="display:none;"></div>
          </div>
        `);
        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(idHTML, idParada, codLinea, linNom) {
      const box = document.getElementById(`res-${idHTML.replace(/[^a-zA-Z0-9]/g, '')}`);
      if (box) {
        box.style.display = 'block';
        box.innerHTML = `<em>Conectando satélite...</em>`;
      }

      try {
        const r = await fetch(`/api/parada?id=${idParada}&cod=${codLinea}&linea=${linNom}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          if (box) box.innerHTML = `No hay unidades en camino.`;
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:4px;"><strong>${a.ramal}</strong><br><span style="color:#27ae60; font-weight:800;">Llega en ${a.tiempo}</span></div>`;
          });
          if (box) box.innerHTML = h;
          pedirDatos(); 
        }
      } catch (e) {
        if (box) box.innerHTML = 'Error de conexión.';
      }
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea] || !RUTAS_GEO[linea][sentidoCode]) return;

      let color = "#89B4FA";
      if (linea === "50A") color = "#A6E3A1";
      if (linea === "50R") color = "#CBA6F7";
      if (linea === "URBANO") color = "#F9E2AF";

      capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoCode], { color: color, weight: 6, opacity: 0.8, lineJoin: 'round' }));
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

    function pedirDatosForzado() {
      const btn = document.getElementById('btn');
      btn.style.opacity = '0.5';
      btn.disabled = true;
      pedirDatos().finally(() => {
        setTimeout(() => { btn.style.opacity = '1'; btn.disabled = false; }, 2000);
      });
    }

    async function pedirDatos() {
      try {
        const r = await fetch('/api/radar');
        const d = await r.json();
        document.getElementById('status').innerText = `Actualizado: ${d.timestamp}`;
        motorPrediccionUber(d.buses);
      } catch (e) {}
    }

    // MOTOR PREDICTIVO (Dead Reckoning + Interpolación suave)
    function motorPrediccionUber(busesNuevos) {
      const label = document.getElementById('bus-count');
      label.innerText = busesNuevos.length > 0 ? `🚌 ${busesNuevos.length} colectivos en vivo` : "Buscando satélites...";

      const idsRecibidos = new Set();
      const ahora = Date.now();

      busesNuevos.forEach(b => {
        idsRecibidos.add(b.id);
        
        if (!stateBuses[b.id]) {
          // Colectivo Nuevo
          let clase = "bus-marker-50b";
          if (b.linea === "50A") clase = "bus-marker-50a";
          if (b.linea === "50R") clase = "bus-marker-50r";
          if (b.linea === "URBANO") clase = "bus-marker-urbano";

          const icon = L.divIcon({
            className: 'custom-icon',
            html: `<div class="bus-marker ${clase}" id="icon-${b.id}">🚌 ${b.linea}</div>`,
            iconSize: [60, 24], iconAnchor: [30, 12]
          });

          const m = L.marker([b.lat, b.lon], { icon: icon });
          m.on('click', () => mostrarRuta(b.linea, b.sentido_code));
          m.addTo(map);

          stateBuses[b.id] = { marker: m, lat: b.lat, lon: b.lon, last_update: ahora, data: b };
          actualizarPopup(stateBuses[b.id]);
        } else {
          // Colectivo Existente: Interpolar movimiento si cambió la posición
          const st = stateBuses[b.id];
          st.data = b;
          
          if (st.lat !== b.lat || st.lon !== b.lon) {
            st.last_update = ahora;
            animarMarcador(st.marker, st.lat, st.lon, b.lat, b.lon, b.id);
            st.lat = b.lat;
            st.lon = b.lon;
          }
          
          actualizarPopup(st);
        }
      });

      // Evaluar estados de demora (Semáforo o Avería)
      for (let id in stateBuses) {
        if (!idsRecibidos.has(id)) {
          // Si desapareció de la API, lo borramos del mapa
          if (animators[id]) cancelAnimationFrame(animators[id]);
          map.removeLayer(stateBuses[id].marker);
          delete stateBuses[id];
        } else {
          // Calcular demora
          const tiempoSinMoverse = (ahora - stateBuses[id].last_update) / 1000;
          const iconDiv = document.getElementById(`icon-${id}`);
          
          if (iconDiv) {
            iconDiv.classList.remove('bus-warning', 'bus-danger');
            let iconoExtra = '';
            
            if (tiempoSinMoverse > 120) {
              iconDiv.classList.add('bus-danger'); // Rojo: Averiado o cortó transmisión
              iconoExtra = ' ⚠️';
            } else if (tiempoSinMoverse > 60) {
              iconDiv.classList.add('bus-warning'); // Naranja: Tráfico pesado o semáforo
              iconoExtra = ' 🚦';
            }
            
            iconDiv.innerHTML = `🚌 ${stateBuses[id].data.linea}${iconoExtra}`;
          }
        }
      }
    }

    function actualizarPopup(st) {
      const b = st.data;
      const tiempoSinMoverse = (Date.now() - st.last_update) / 1000;
      let estadoTxt = `<span style="color:#27ae60;">🟢 En movimiento</span>`;
      
      if (tiempoSinMoverse > 120) {
        estadoTxt = `<span style="color:#F38BA8;">🔴 Detenido / Sin conexión</span>`;
      } else if (tiempoSinMoverse > 60) {
        estadoTxt = `<span style="color:#FAB387;">🟠 Tráfico / Parada</span>`;
      }

      const popup = `
        <div style="font-family:sans-serif; font-size:12px; min-width: 150px;">
          <strong style="font-size:15px; color:#111;">Línea ${b.linea}</strong><br>
          <span style="color:#555; font-weight:700;">${b.sentido}</span><br>
          <div style="margin: 6px 0; padding: 4px; background: #f4f4f4; border-radius: 4px;">
            ${estadoTxt}
          </div>
          <span style="color:#111; font-weight:bold;">⏱️ Arribo predictivo: ${b.tiempo_arribo || '--'}</span>
        </div>
      `;
      st.marker.bindPopup(popup);
    }

    function animarMarcador(marker, startLat, startLon, endLat, endLon, id) {
      if (animators[id]) cancelAnimationFrame(animators[id]);
      
      const duration = 4000; // 4 segundos de deslizamiento suave (simula la velocidad en calle)
      let startTime = null;

      function step(timestamp) {
        if (!startTime) startTime = timestamp;
        const progress = Math.min((timestamp - startTime) / duration, 1);
        
        // Easing (arranca rápido, frena suave en el semáforo/parada)
        const easeOutQuad = progress * (2 - progress);
        
        const currentLat = startLat + (endLat - startLat) * easeOutQuad;
        const currentLon = startLon + (endLon - startLon) * easeOutQuad;
        
        marker.setLatLng([currentLat, currentLon]);

        if (progress < 1) {
          animators[id] = requestAnimationFrame(step);
        }
      }
      animators[id] = requestAnimationFrame(step);
    }

    init();
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
