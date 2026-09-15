import os
import time
import json
import math
import requests
from datetime import datetime
import zoneinfo
from threading import Thread
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Cargar paradas y trazas con rutas seguras
with open(os.path.join(BASE_DIR, "paradas_optimizadas.json"), "r", encoding="utf-8") as f:
    PARADAS_RAW = json.load(f)

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

# 2. Agrupar paradas que estén a menos de 35 metros (evita 4 botones en una esquina)
def agrupar_paradas(paradas, radio_mts=35):
    grupos = []
    for p in paradas:
        id_p, lat, lon, desc, lineas = p
        unido = False
        for g in grupos:
            d_lat = (lat - g["lat"]) * 111139
            d_lon = (lon - g["lon"]) * 111139 * 0.777
            if math.sqrt(d_lat**2 + d_lon**2) <= radio_mts:
                for lin_nom, lin_cod in lineas.items():
                    if lin_nom not in g["lineas"]:
                        g["lineas"][lin_nom] = {"cod": lin_cod, "parada": id_p}
                if id_p not in g["ids"]:
                    g["ids"].append(id_p)
                unido = True
                break
        if not unido:
            grupos.append({
                "ids": [id_p],
                "lat": lat,
                "lon": lon,
                "desc": desc,
                "lineas": {lin_nom: {"cod": lin_cod, "parada": id_p} for lin_nom, lin_cod in lineas.items()}
            })
    return [
        [" / ".join(g["ids"][:2]), g["lat"], g["lon"], g["desc"], g["lineas"]]
        for g in grupos
    ]

PARADAS_CLUSTERIZADAS = agrupar_paradas(PARADAS_RAW)

URL_WORKER = "https://radar-colectivos.gorolol.workers.dev/"

# Estado global con tracker persistente de unidades
ESTADO_GLOBAL = {
    "timestamp": "--:--:--",
    "buses": {}, # key: bus_id -> datos
    "contador_ids": 1
}

def distancia_km(lat1, lon1, lat2, lon2):
    d_lat = (lat1 - lat2) * 111.0
    d_lon = (lon1 - lon2) * 111.0 * 0.777
    return math.sqrt(d_lat**2 + d_lon**2)

def procesar_nuevas_posiciones(detecciones):
    global ESTADO_GLOBAL
    ahora = time.time()

    for d in detecciones:
        lat = d.get("lat")
        lon = d.get("lon")
        linea = d.get("linea")
        if not lat or not lon or not linea:
            continue

        # 1. Buscar si esta posición corresponde a un colectivo existente (a menos de 1.8 km)
        bus_match_id = None
        min_dist = 1.8
        for b_id, b in ESTADO_GLOBAL["buses"].items():
            if b["linea"] == linea:
                dist = distancia_km(b["lat"], b["lon"], lat, lon)
                if dist < min_dist:
                    min_dist = dist
                    bus_match_id = b_id

        if bus_match_id:
            # Colectivo existente que avanzó: determinar sentido por desplazamiento real
            bus = ESTADO_GLOBAL["buses"][bus_match_id]
            delta_lon = lon - bus["lon"]

            if abs(delta_lon) > 0.0003: # Se movió al menos 25 metros
                if delta_lon < 0: # Longitud más negativa = va al Oeste (Plottier)
                    sentido = "Hacia Plottier"
                    sentido_code = "HACIA_PLOTTIER"
                else: # Longitud menos negativa = va al Este (Neuquén)
                    sentido = "Hacia Neuquén"
                    sentido_code = "HACIA_NEUQUEN"
            else:
                sentido = bus["sentido"]
                sentido_code = bus["sentido_code"]

            bus.update({
                "lat": lat,
                "lon": lon,
                "sentido": sentido,
                "sentido_code": sentido_code,
                "tiempo_arribo": d.get("tiempo_arribo") or bus.get("tiempo_arribo"),
                "updated_at": ahora
            })
        else:
            # Nuevo colectivo detectado
            nuevo_id = f"{linea}_{ESTADO_GLOBAL['contador_ids']}"
            ESTADO_GLOBAL["contador_ids"] += 1

            # Sentido inicial por comparación de cercanía a la traza IDA / VUELTA
            sentido = "Hacia Plottier"
            sentido_code = "HACIA_PLOTTIER"
            if linea in TRAZAS_GEO:
                pts_vuelta = TRAZAS_GEO[linea].get("HACIA_NEUQUEN", [])
                pts_ida = TRAZAS_GEO[linea].get("HACIA_PLOTTIER", [])
                d_vuelta = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_vuelta], default=99)
                d_ida = min([distancia_km(lat, lon, p[0], p[1]) for p in pts_ida], default=99)
                if d_vuelta < d_ida:
                    sentido = "Hacia Neuquén"
                    sentido_code = "HACIA_NEUQUEN"

            ESTADO_GLOBAL["buses"][nuevo_id] = {
                "id": nuevo_id,
                "linea": linea,
                "ramal": d.get("ramal") or f"Línea {linea}",
                "sentido": sentido,
                "sentido_code": sentido_code,
                "tiempo_arribo": d.get("tiempo_arribo"),
                "lat": lat,
                "lon": lon,
                "updated_at": ahora
            }

    # Eliminar unidades sin reporte tras 75 segundos (evita fantasmas en fila)
    ESTADO_GLOBAL["buses"] = {
        k: v for k, v in ESTADO_GLOBAL["buses"].items()
        if ahora - v["updated_at"] < 75
    }

def recolector_fondo():
    global ESTADO_GLOBAL
    while True:
        try:
            r = requests.get(URL_WORKER, timeout=12)
            if r.status_code == 200:
                data = r.json()
                procesar_nuevas_posiciones(data.get("buses", []))
        except Exception:
            pass

        try:
            tz = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")
            ESTADO_GLOBAL["timestamp"] = datetime.now(tz).strftime("%H:%M:%S")
        except Exception:
            ESTADO_GLOBAL["timestamp"] = time.strftime("%H:%M:%S")

        time.sleep(12)

Thread(target=recolector_fondo, daemon=True).start()

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
            arribos = data.get("arribos", [])
            # Inyectar las posiciones descubiertas al radar
            procesar_nuevas_posiciones([
                {**a, "linea": p_linea, "tiempo_arribo": a.get("tiempo")}
                for a in arribos if a.get("lat") and a.get("lon")
            ])
            return jsonify({"arribos": arribos})
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
    return jsonify({
        "trazas": TRAZAS_GEO,
        "paradas": PARADAS_CLUSTERIZADAS
    })

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
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 95px; }
    header { margin-bottom: 12px; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; }
    #map { height: 440px; width: 100%; background: #11111B; }
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.9); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #CDD6F4; border: 1px solid #313244; font-weight: 700; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .btn-map-control { background: rgba(24, 24, 37, 0.9); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 10px; cursor: pointer; }
    .status-text { font-size: 12px; color: #A6ADC8; }

    /* Los marcadores NO usan transform transition para no romper el zoom */
    .bus-marker { display: flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 2px 6px rgba(0,0,0,0.6); }
    .bus-marker-50a { background: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background: #38243E; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background: #3E3724; border: 2px solid #F9E2AF; color: #F9E2AF; }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 6px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px; }
    .result-box { margin-top: 6px; padding-top: 4px; border-top: 1px solid #ccc; font-size: 11px; color: #111; }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS en vivo (50A, 50B, 50R y Urbano)</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRutas()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
    <div id="map"></div>
  </div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-text" id="status">Sincronizando...</div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map, capaRuta, capaParadas;
    let marcadoresBuses = {};
    let RUTAS_GEO = {};
    let mostrandoParadas = true;

    async function init() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.18], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      const r = await fetch('/api/static_data');
      const staticData = await r.json();
      RUTAS_GEO = staticData.trazas;

      dibujarParadas(staticData.paradas);
      pedirDatos();
      setInterval(pedirDatos, 12000);
    }

    function dibujarParadas(paradas) {
      capaParadas.clearLayers();
      paradas.forEach(p => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        let botones = '';
        for (const [linNom, info] of Object.entries(lineas)) {
          botones += `<button class="btn-query-stop" onclick="consultarParada('${info.parada}', '${info.cod}', '${linNom}')">⏱️ ${linNom}</button>`;
        }

        const marker = L.circleMarker([lat, lon], {
          radius: 4.5, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.85, weight: 1.5
        });

        marker.bindPopup(`
          <div style="min-width:160px;">
            <div class="stop-popup-title">📍 ${desc}</div>
            <div class="stop-popup-desc">Ref: ${id}</div>
            <div>${botones}</div>
            <div id="res-${id}" class="result-box" style="display:none;"></div>
          </div>
        `);
        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(idParada, codLinea, linNom) {
      const box = document.querySelector('.leaflet-popup-content .result-box');
      if (box) {
        box.style.display = 'block';
        box.innerHTML = `<em>Consultando arribos de ${linNom}...</em>`;
      }

      try {
        const r = await fetch(`/api/parada?id=${idParada}&cod=${codLinea}&linea=${linNom}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          if (box) box.innerHTML = `Sin arribos próximos para ${linNom}.`;
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:3px;"><strong>${a.ramal}</strong> (${a.sentido})<br>Arribo: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span></div>`;
          });
          if (box) box.innerHTML = h;
          pedirDatos();
        }
      } catch (e) {
        if (box) box.innerHTML = 'Error al consultar parada.';
      }
    }

    // Animación fluida nativa vía requestAnimationFrame (no se descalibra con el zoom)
    function deslizarMarcador(marker, destLat, destLon) {
      const from = marker.getLatLng();
      const to = L.latLng(destLat, destLon);
      if (from.distanceTo(to) < 1) return;
      if (from.distanceTo(to) > 2500) { marker.setLatLng(to); return; }

      let start = null;
      const duration = 1200;

      function step(timestamp) {
        if (!start) start = timestamp;
        const progress = Math.min((timestamp - start) / duration, 1);
        const lat = from.lat + (to.lat - from.lat) * progress;
        const lon = from.lng + (to.lng - from.lng) * progress;
        marker.setLatLng([lat, lon]);
        if (progress < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea] || !RUTAS_GEO[linea][sentidoCode]) return;

      let color = "#89B4FA";
      if (linea === "50A") color = "#A6E3A1";
      if (linea === "50R") color = "#CBA6F7";
      if (linea === "URBANO") color = "#F9E2AF";

      capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoCode], { color: color, weight: 5, opacity: 0.9 }));
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

    async function pedirDatos() {
      try {
        const r = await fetch('/api/radar');
        const d = await r.json();
        document.getElementById('status').innerText = `Actualizado: ${d.timestamp}`;
        actualizarBuses(d.buses);
      } catch (e) {}
    }

    function actualizarBuses(buses) {
      const label = document.getElementById('bus-count');
      label.innerText = buses.length > 0 ? `🚌 ${buses.length} colectivos en vivo` : "Buscando unidades en recorrido...";

      const idsActivos = new Set();
      buses.forEach(b => {
        idsActivos.add(b.id);
        let clase = "bus-marker-50b";
        if (b.linea === "50A") clase = "bus-marker-50a";
        if (b.linea === "50R") clase = "bus-marker-50r";
        if (b.linea === "URBANO") clase = "bus-marker-urbano";

        const icon = L.divIcon({
          className: 'custom-icon',
          html: `<div class="bus-marker ${clase}">🚌 ${b.linea}</div>`,
          iconSize: [58, 24], iconAnchor: [29, 12]
        });

        const colorSentido = b.sentido_code === 'HACIA_NEUQUEN' ? '#FAB387' : '#A6E3A1';
        const popup = `
          <div style="font-family:sans-serif; font-size:12px;">
            <strong style="font-size:14px;">Línea ${b.linea}</strong><br>
            <span style="color:${colorSentido}; font-weight:700;">${b.sentido}</span><br>
            <span style="color:#666;">${b.ramal}</span>
            <div style="color:#27ae60; font-weight:bold; margin-top:4px;">⏱️ Arribo: ${b.tiempo_arribo || 'En camino'}</div>
          </div>
        `;

        if (marcadoresBuses[b.id]) {
          deslizarMarcador(marcadoresBuses[b.id], b.lat, b.lon);
          marcadoresBuses[b.id].getPopup().setContent(popup);
        } else {
          const m = L.marker([b.lat, b.lon], { icon: icon });
          m.bindPopup(popup);
          m.on('click', () => mostrarRuta(b.linea, b.sentido_code));
          m.addTo(map);
          marcadoresBuses[b.id] = m;
        }
      });

      for (let id in marcadoresBuses) {
        if (!idsActivos.has(id)) {
          map.removeLayer(marcadoresBuses[id]);
          delete marcadoresBuses[id];
        }
      }
    }

    init();
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
