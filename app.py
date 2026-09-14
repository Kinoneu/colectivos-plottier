import os
import re
import time
import math
import threading
import urllib3
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, render_template_string
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

URL_PAGINA = "https://cuandollega.smartmovepro.net/indalo/recorridos"
URL_API = f"{URL_PAGINA}?handler=Arribos"

# Cabeceras y paradas de barrido central
CONSULTAS_RADAR = [
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
session_lock = threading.Lock()

CACHE_TTL = 18
TIEMPO_PERDIDO = 85
TIEMPO_EXPIRAR = 200

flota_memoria = {}
cabeceras_memoria = {}
cache_paradas_click = {}  # Cache temporal de 12s para consultas individuales de postes
ultima_hora_sync = "--:--:--"
ultimo_escaneo_ts = 0

def obtener_hora_arg():
    tz_arg = timezone(timedelta(hours=-3))
    return datetime.now(tz_arg).strftime("%H:%M:%S")

def calcular_distancia(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111.0

def renovar_token_unlocked():
    global csrf_token
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

def consultar_arribos_api(parada, cod_linea):
    global csrf_token
    with session_lock:
        if not csrf_token:
            renovar_token_unlocked()
        
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
                renovar_token_unlocked()
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
  <title>Líneas 50A / 50B - Plottier</title>
  
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
    #map { height: 330px; width: 100%; background: #11111B; }
    
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.92); backdrop-filter: blur(6px); padding: 5px 12px; border-radius: 8px; font-size: 11px; color: #CDD6F4; border: 1px solid #313244; font-weight: 600; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; }
    .map-btn { background: rgba(24, 24, 37, 0.92); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 12px; border-radius: 8px; cursor: pointer; backdrop-filter: blur(6px); }

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

    /* Estilo para las paradas circulares en el mapa */
    .stop-marker-circle {
      background: #CDD6F4;
      border: 2px solid #181825;
      border-radius: 50%;
      box-shadow: 0 0 4px rgba(0,0,0,0.5);
      cursor: pointer;
    }
  </style>
</head>
<body>
  <header>
    <h1>Transporte Plottier</h1>
    <p class="sub">GPS en vivo y paradas interactivas (50A y 50B)</p>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando flota...</div>
    <div class="map-controls">
      <button class="map-btn" id="btn-toggle-stops" onclick="alternarParadas()">🚏 Ver Paradas</button>
      <button class="map-btn" id="btn-clear" onclick="limpiarRuta()" style="display:none;">✕ Quitar ruta</button>
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
      <div id="hint" class="cached-hint">Tocá cualquier parada para ver su arribo</div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <script>
    function mercatorALatLon(x, y) {
      const lon = (x / 20037508.34) * 180;
      let lat = (y / 20037508.34) * 180;
      lat = 180 / Math.PI * (2 * Math.atan(Math.exp(lat * Math.PI / 180)) - Math.PI / 2);
      return [lat, lon];
    }

    const TRAZAS_RAW = {
      "50B": {
        "HACIA_PLOTTIER": [[-7576123.127717475,-4713953.225682237],[-7576127.135219142,-4713960.668571745],[-7576140.270919057,-4714625.541017488],[-7575523.672259552,-4714622.5350375585],[-7575533.913652705,-4715537.968661558],[-7578334.266763101,-4715525.657356469],[-7578412.190406656,-4715517.9270097455],[-7578498.129053549,-4715523.939501133],[-7578494.566829843,-4715600.956967883],[-7579108.493821568,-4715589.933986044],[-7579115.72958847,-4715842.177166955],[-7583422.0127703175,-4715796.366361502],[-7583523.090867958,-4715778.757888199],[-7583546.913238986,-4715779.473679201],[-7583639.5310553275,-4715757.141023744],[-7583717.454698882,-4715733.949472043],[-7583945.325696536,-4715679.120273622],[-7584124.772715694,-4715657.360465009],[-7584513.611697037,-4715650.345799814],[-7584585.078810125,-4715654.067866457],[-7584684.821073875,-4715642.042732994],[-7586734.21289938,-4715629.015521161],[-7586895.51484154,-4715621.7145636035],[-7587297.155564321,-4715619.280912253],[-7588442.187846622,-4715419.723488214],[-7588664.270230753,-4715194.25981618],[-7590284.970697214,-4713564.914808015],[-7590591.87853333,-4714429.581617774],[-7590632.510147468,-4714417.701074614],[-7590624.4951441325,-4713756.849877528],[-7594854.635794276,-4713713.624809864],[-7594851.518848535,-4712383.6136334315],[-7596173.103843232,-4712371.878595528],[-7596505.837801212,-4712371.306155002],[-7596507.062315612,-4712007.097415341],[-7596821.09459914,-4712010.675040777],[-7596824.768142336,-4711714.451925238],[-7597492.351128625,-4711704.291768824],[-7597495.690713347,-4711684.114586941],[-7597586.861376307,-4711683.685285635],[-7597684.154611261,-4711690.840309779],[-7597727.45789318,-4711685.545591426],[-7597782.672360612,-4711685.259390514],[-7597844.788636475,-4711680.966377784],[-7597998.52085326,-4711678.390571015],[-7598051.731569858,-4711679.249173199],[-7598168.394396211,-4711676.244065874],[-7598169.618910611,-4711685.545591426],[-7598514.820651559,-4711685.974892813],[-7598512.816900725,-4712308.0516757555],[-7598463.279727323,-4712301.611762196],[-7598446.470484212,-4712292.166563034],[-7598173.626412278,-4712256.103156181],[-7598125.425072765,-4712247.65975801],[-7598058.85601727,-4712240.361233048],[-7597865.271422781,-4712214.744883052],[-7597575.506788245,-4712170.810846718],[-7597547.676915548,-4712165.9451996675],[-7597528.752602113,-4712163.798591416],[-7597513.947109837,-4712164.943449095],[-7597508.492454789,-4712161.938197968],[-7597509.049052242,-4712127.8787473785],[-7597488.900224409,-4712119.864775614],[-7597477.5456363475,-4712111.850810179],[-7597471.200425373,-4712047.309997799],[-7596829.220921968,-4712055.46701795],[-7596829.220921968,-4712382.75497166],[-7596173.437801706,-4712373.16658683],[-7596170.654814434,-4713035.3588711675],[-7595380.954346748,-4713041.083652457],[-7595378.505317951,-4713714.054197047],[-7594863.763992522,-4713715.342358708],[-7594864.097950994,-4714610.94055188],[-7595153.1946685845,-4714615.807371415],[-7595602.257494444,-4714856.431565999],[-7595629.085491726,-4714867.740041546],[-7595630.866603578,-4714928.720139591],[-7595924.750059273,-4714929.292724408],[-7596190.469683797,-4714997.287401224],[-7596213.178859917,-4715768.307345327],[-7596826.437934698,-4715759.288392326],[-7596826.437934698,-4715656.644682625],[-7597004.326480986,-4715716.341107085],[-7597005.550995384,-4715740.248406765],[-7597262.2537411535,-4715780.332628469]],
        "HACIA_NEUQUEN": [[-7597262.2537411535,-4715780.332628469],[-7597261.585824208,-4715793.78950984],[-7597226.854143082,-4716016.403276067],[-7597064.327686524,-4715986.482556415],[-7596989.4096692195,-4715979.467663623],[-7596961.802435502,-4715989.202618192],[-7596826.66057368,-4715988.773134706],[-7596820.649321177,-4716600.519214987],[-7596475.558899717,-4716534.374985973],[-7596227.093796266,-4716495.71946742],[-7596221.97309969,-4716454.200741217],[-7596218.633514967,-4716119.909604224],[-7596222.084419181,-4715995.358550169],[-7594918.31054301,-4715996.933324063],[-7594907.623871894,-4715503.468414098],[-7594600.827355268,-4715459.233828643],[-7594473.700496783,-4715407.8417855],[-7594294.253477624,-4715367.759035632],[-7594121.374308422,-4715348.004024316],[-7593282.804584275,-4715345.999894883],[-7593272.340552142,-4715328.678506993],[-7588935.667149306,-4715362.032941436],[-7588411.018389199,-4715449.356229109],[-7587310.959181179,-4715648.771079722],[-7584045.624557742,-4715682.126566638],[-7583538.452957686,-4715799.945323227],[-7580364.734275171,-4715848.762487246],[-7580187.402326336,-4715861.64682192],[-7580145.65751729,-4715862.362618769],[-7580125.286050473,-4715872.240620467],[-7579728.988663251,-4715861.074184476],[-7579426.756245745,-4715880.1143968245],[-7579110.608891894,-4715874.388013413],[-7579107.046668188,-4715591.079230352],[-7578495.012107806,-4715600.098033803],[-7578493.787593408,-4715677.688705831],[-7577255.692216804,-4715681.840252981],[-7577108.193891504,-4715689.284410742],[-7576301.684180708,-4715700.021186369],[-7576299.3464714,-4715234.198730027],[-7575988.765092087,-4715237.920643987],[-7575978.078420971,-4713612.4330702275],[-7576128.916330996,-4713616.011261632],[-7576123.127717475,-4713953.225682237]]
      },
      "50A": {
        "HACIA_PLOTTIER": [[-7576123.127717475,-4713953.225682237],[-7576126.801260672,-4713962.24302984],[-7576139.269043639,-4714629.119566186],[-7575523.672259552,-4714622.248753801],[-7575532.243860344,-4715533.817173289],[-7576644.770851331,-4715532.09931657],[-7576650.893423325,-4715841.890848778],[-7577570.503736769,-4715836.450804959],[-7577572.618807093,-4715854.775174725],[-7583421.567492354,-4715798.943213817],[-7583560.828175335,-4715775.751566543],[-7583874.860458863,-4715693.006491674],[-7583955.121811725,-4715674.968727586],[-7584108.9653480025,-4715654.497335772],[-7584605.895554903,-4715650.202643431],[-7584680.479613734,-4715639.609076765],[-7587213.443307246,-4715620.139847957],[-7587287.6934076045,-4715615.98832606],[-7587825.1439091535,-4715524.941583376],[-7587911.973111974,-4715501.464253952],[-7588335.989052405,-4715432.607277967],[-7588433.282287358,-4715422.8728575315],[-7588473.2459845515,-4715410.847998125],[-7588863.4207997825,-4715348.719784924],[-7588928.320062916,-4715342.134789236],[-7589020.158642819,-4715337.553925193],[-7589548.258307143,-4715331.3983923895],[-7589632.638481165,-4715333.688822764],[-7590323.70988001,-4715321.807220816],[-7590518.518988898,-4715328.964810683],[-7591577.835263286,-4715320.089399999],[-7591637.613829843,-4715316.796910914],[-7593305.179801925,-4715308.350965536],[-7593380.877055665,-4715311.929755093],[-7594183.935862247,-4715296.898847442],[-7594201.413022301,-4715297.041998837],[-7594240.597483061,-4715293.320063189],[-7594253.176585521,-4715294.322122653],[-7594704.6884401785,-4715455.082372595],[-7594728.6221306985,-4715460.235904495],[-7594785.729029476,-4715461.524287879],[-7594910.963456619,-4715483.999446573],[-7594907.623871894,-4715503.468414098],[-7594908.40310833,-4715525.084737992],[-7594910.852137129,-4715545.985333369],[-7594911.742693054,-4715715.195848635],[-7594915.8615142135,-4715756.997865855],[-7594920.870891299,-4715997.07648534],[-7594941.242358114,-4715995.501711421],[-7596194.922463427,-4715989.202618192],[-7596224.422128488,-4715996.074356453],[-7596222.195738672,-4716125.492963153],[-7596224.978725942,-4716307.168549865],[-7596222.752336126,-4716466.083669633],[-7596229.542825065,-4716492.999269811],[-7596813.413554275,-4716592.501709711],[-7596817.643694925,-4716592.215370353],[-7596825.770017753,-4715985.480428577],[-7596942.3215246145,-4715989.345779359],[-7596959.576045686,-4715989.202618192],[-7596967.591049024,-4715980.040307751],[-7596987.851196348,-4715976.747604458],[-7597026.145101181,-4715979.038180549],[-7597225.518309192,-4716011.535784564],[-7597259.582073375,-4715789.065283496],[-7597261.140546246,-4715786.917908611]],
        "HACIA_NEUQUEN": [[-7597250.119916658,-4715779.759995615],[-7597007.220787747,-4715742.538929453],[-7597004.103842004,-4715719.920040578],[-7596845.584887113,-4715664.947761397],[-7596828.553005023,-4715661.798316925],[-7596830.111477895,-4715759.002076489],[-7596504.168008851,-4715759.002076489],[-7596297.113755976,-4715770.884190514],[-7596210.395872649,-4715769.738925908],[-7596208.948719267,-4715766.875764949],[-7596206.611009962,-4715726.362124044],[-7596207.056287925,-4715632.451267713],[-7596197.705450697,-4715475.410208072],[-7596190.803642267,-4715001.009228269],[-7596188.688571943,-4714998.862020193],[-7595976.06834453,-4714941.603305795],[-7595930.761311775,-4714931.153625288],[-7595916.289777972,-4714929.722163043],[-7595639.772162842,-4714928.720139591],[-7595630.866603578,-4714922.135416516],[-7595635.3193832105,-4714889.35501089],[-7595631.9797984855,-4714870.602948748],[-7595618.064862136,-4714861.298503298],[-7595474.462719014,-4714812.915524512],[-7595452.421459837,-4714803.897420843],[-7595426.372698991,-4714789.439842796],[-7595328.745505566,-4714729.462585574],[-7595255.6086001145,-4714677.7879537875],[-7595245.36720696,-4714667.767972549],[-7595192.04517087,-4714632.984400197],[-7595172.564259982,-4714622.391895678],[-7595141.283483069,-4714613.230819607],[-7595096.755686752,-4714609.938559915],[-7594860.090449327,-4714611.226835318],[-7594858.865934927,-4714425.573722142],[-7594861.203644233,-4714366.600583722],[-7594859.867810343,-4713727.508338012],[-7594861.426283215,-4713711.764132275],[-7594881.797750031,-4713708.901552039],[-7595029.073436349,-4713712.193519382],[-7595138.945773764,-4713710.046584037],[-7595198.167742864,-4713705.8958436595],[-7595380.843027256,-4713707.470262223],[-7595379.061915404,-4713042.944207072],[-7595412.903040605,-4713040.797413317],[-7596165.088839895,-4713036.074468653],[-7596175.218913556,-4713035.6451101545],[-7596171.656689852,-4712581.966448992],[-7596175.441552539,-4712540.893072966],[-7596172.881204251,-4712379.320325308],[-7596175.107594066,-4712373.452807142],[-7596197.482811715,-4712371.592375263],[-7596824.545503356,-4712377.889223004],[-7596822.541752521,-4712057.756708993],[-7596881.095804678,-4712054.608383941],[-7597470.75514741,-4712047.309997799],[-7597479.660706673,-4712111.850810179],[-7597506.600023445,-4712129.166707716],[-7597508.381135297,-4712165.9451996675],[-7597617.028958312,-4712176.678247733],[-7598443.798816433,-4712290.449255041],[-7598466.507992555,-4712302.470417102],[-7598512.14898378,-4712306.191255862],[-7598514.709332068,-4711685.11629006],[-7598174.071690242,-4711687.4058975605],[-7598167.8377987575,-4711688.24747066],[-7598050.173096989,-4711681.681879779],[-7598003.752869328,-4711673.382059729],[-7597996.628421916,-4711680.250875837],[-7597786.123264827,-4711683.11288392],[-7597676.250927414,-4711692.700616881],[-7597591.202836447,-4711686.976596114],[-7597495.802032838,-4711686.976596114],[-7597490.681336261,-4711704.577970274],[-7597171.528356157,-4711708.727892203],[-7597137.909869937,-4711711.160605849],[-7596828.886963496,-4711713.593320077],[-7596821.985155067,-4711712.73471499],[-7596823.209669465,-4712007.526730327],[-7596508.06419103,-4712008.099150336],[-7596506.839676631,-4712376.028790309],[-7596181.11884657,-4712375.456349549],[-7596140.153273959,-4712379.320325308],[-7594850.628292607,-4712383.041192242],[-7594857.1961425645,-4712652.664565672],[-7594854.301835804,-4712803.221710374],[-7594862.09420016,-4713066.272728497],[-7594856.52822562,-4713349.654142329],[-7594859.867810343,-4713652.652014227],[-7594857.864059509,-4713715.485487791],[-7594743.650261955,-4713720.495006986],[-7594475.815567107,-4713722.785073727],[-7594427.614227593,-4713725.9339163415],[-7593642.366539538,-4713726.649562525],[-7593624.5554210115,-4713727.365208761],[-7593504.775648918,-4713719.922490382],[-7590854.25857313,-4713736.954873182],[-7590688.83780981,-4713749.407137522],[-7590621.266878899,-4713750.55217409],[-7590628.057367837,-4714427.434530633],[-7590588.427629116,-4714428.8659220105],[-7590470.428968875,-4714075.60465476],[-7590274.840623551,-4713565.201061941],[-7589298.012091841,-4714546.383843045],[-7589235.339218523,-4714600.92063666],[-7589116.338682866,-4714738.194336053],[-7588664.270230753,-4715194.25981618],[-7588577.774986408,-4715295.037879472],[-7588495.509882711,-4715372.196760856],[-7588405.118456188,-4715449.069922021],[-7587364.949134214,-4715630.590238186],[-7587261.533327267,-4715639.609076765],[-7585866.366149155,-4715643.044826904],[-7584155.385575662,-4715668.669833398],[-7583959.240632885,-4715693.435962638],[-7583560.048938901,-4715785.056850747],[-7583538.452957686,-4715799.945323227],[-7580226.475467606,-4715852.0551489955],[-7580186.51177041,-4715861.64682192],[-7580147.438629141,-4715861.64682192],[-7580123.282299641,-4715871.811141933],[-7579722.754771766,-4715863.078415671],[-7579662.419607755,-4715869.520590055],[-7579114.39375458,-4715874.388013413],[-7579106.935348698,-4715591.508697],[-7578491.561203592,-4715601.10012357],[-7578492.897037482,-4715678.977116833],[-7576303.242653578,-4715692.004392827],[-7576297.231401076,-4715693.292805648],[-7576297.342720565,-4715231.19256975],[-7576244.799920911,-4715237.204891196],[-7576147.72932494,-4715244.219270719],[-7575989.433009031,-4715241.499408697],[-7575987.87453616,-4715235.9165362995],[-7575991.548079357,-4715061.990127367],[-7575984.757590419,-4714937.595207889],[-7575987.095299726,-4714799.316799827],[-7575985.759465835,-4714749.932110833],[-7575975.963350645,-4714629.548992114],[-7575981.195366712,-4714455.9192570355],[-7575977.187865044,-4714218.453556359],[-7575975.963350645,-4714202.136045013],[-7575973.291682867,-4713941.345696835],[-7575971.176612541,-4713898.97863323],[-7575975.963350645,-4713611.00179402],[-7576126.022024234,-4713610.429283593],[-7576127.580497106,-4713825.266089471],[-7576125.910704744,-4713913.005546861],[-7576123.127717475,-4713953.225682237]]
      }
    };

    // Lista completa de paradas extraídas directamente del servidor de Indalo (50A)
    const PARADAS_OFICIALES = [
      {"id":"NV1008","desc":"NV1008","lat":-38.959017,"lon":-68.106748,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1010","desc":"NV1010","lat":-38.958888,"lon":-68.117712,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1025","desc":"NV1025","lat":-38.957974,"lon":-68.141026,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1143","desc":"NV1143","lat":-38.957799,"lon":-68.155489,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1029","desc":"NV1029","lat":-38.955654,"lon":-68.192332,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1027","desc":"NV1027","lat":-38.956455,"lon":-68.167527,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1012","desc":"NV1012","lat":-38.956568,"lon":-68.167666,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1013","desc":"NV1013","lat":-38.955613,"lon":-68.178095,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1028","desc":"NV1028","lat":-38.955880,"lon":-68.185664,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1030","desc":"NV1030","lat":-38.955804,"lon":-68.196961,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1031","desc":"NV1031","lat":-38.955563,"lon":-68.208768,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1032","desc":"NV1032","lat":-38.955388,"lon":-68.218424,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1026","desc":"NV1026","lat":-38.957840,"lon":-68.155897,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1011","desc":"NV1011","lat":-38.957999,"lon":-68.139772,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1009","desc":"NV1009","lat":-38.958909,"lon":-68.117123,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1014","desc":"NV1014 (Cabecera Este)","lat":-38.946381,"lon":-68.057601,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1015","desc":"NV1015","lat":-38.949342,"lon":-68.057693,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1016","desc":"NV1016","lat":-38.950777,"lon":-68.056394,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1017","desc":"NV1017","lat":-38.950693,"lon":-68.053841,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1018","desc":"NV2018","lat":-38.951683,"lon":-68.052191,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1019","desc":"NV1019","lat":-38.955511,"lon":-68.052243,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1021","desc":"NV1021","lat":-38.957124,"lon":-68.060420,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1023","desc":"NV1023","lat":-38.957960,"lon":-68.147140,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1024","desc":"NV1024","lat":-38.955619,"lon":-68.195944,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1034","desc":"NV1034","lat":-38.958992,"lon":-68.248224,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1116","desc":"NV1116","lat":-38.959502,"lon":-68.088995,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1117","desc":"NV1117","lat":-38.959225,"lon":-68.095626,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1050","desc":"NV1050","lat":-38.960227,"lon":-68.231994,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1035","desc":"NV1035","lat":-38.964104,"lon":-68.239780,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1038","desc":"NV1038","lat":-38.964520,"lon":-68.243109,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1039","desc":"NV1039","lat":-38.962051,"lon":-68.243420,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1040","desc":"NV1040","lat":-38.960381,"lon":-68.244661,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1041","desc":"NV1041","lat":-38.960362,"lon":-68.227848,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1042","desc":"NV1042","lat":-38.960357,"lon":-68.229405,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1043","desc":"NV1043","lat":-38.960336,"lon":-68.233364,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1044","desc":"NV1044","lat":-38.960239,"lon":-68.236177,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1046","desc":"NV1046","lat":-38.961257,"lon":-68.238108,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1047","desc":"NV1047","lat":-38.963159,"lon":-68.238079,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1048","desc":"NV1048","lat":-38.963915,"lon":-68.238462,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1049","desc":"NV1049","lat":-38.964228,"lon":-68.240999,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1051","desc":"NV1051","lat":-38.960069,"lon":-68.247066,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1052","desc":"NV1052","lat":-38.959130,"lon":-68.249539,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1058","desc":"NV1058","lat":-38.958794,"lon":-68.124248,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1059","desc":"NV1059","lat":-38.958877,"lon":-68.118315,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1060","desc":"NV1060","lat":-38.958078,"lon":-68.134464,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1062","desc":"NV1062","lat":-38.955871,"lon":-68.198951,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1063","desc":"NV1063","lat":-38.955454,"lon":-68.211289,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1066","desc":"NV1066","lat":-38.956680,"lon":-68.226224,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1069","desc":"NV1069","lat":-38.957731,"lon":-68.226288,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1070","desc":"NV1070","lat":-38.957718,"lon":-68.159731,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1071","desc":"NV1071","lat":-38.955713,"lon":-68.175137,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1136","desc":"NV1136","lat":-38.959289,"lon":-68.085507,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV2021","desc":"NV2021","lat":-38.959249,"lon":-68.090370,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV6043","desc":"NV6043","lat":-38.959504,"lon":-68.089109,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"GATICA 299","desc":"Gatica y Mosconi","lat":-38.959279,"lon":-68.073504,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"RIVAS299","desc":"Rivas y Mosconi","lat":-38.959302,"lon":-68.079020,"cod":1013,"linea":"50A","sentido":"Hacia Neuquén"},
      {"id":"NV1194","desc":"NV1194","lat":-38.950315,"lon":-68.175466,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1195","desc":"NV1195","lat":-38.946710,"lon":-68.180058,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1201","desc":"NV1201","lat":-38.949172,"lon":-68.187418,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1202","desc":"NV1202","lat":-38.947912,"lon":-68.187633,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1204","desc":"NV1204","lat":-38.946477,"lon":-68.187665,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1205","desc":"NV1205","lat":-38.944908,"lon":-68.187633,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1160","desc":"NV1160","lat":-38.944516,"lon":-68.215055,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1150","desc":"NV1150","lat":-38.944657,"lon":-68.197331,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1199","desc":"NV1199","lat":-38.946435,"lon":-68.186013,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1198","desc":"NV1198","lat":-38.944849,"lon":-68.185261,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1197","desc":"NV1197","lat":-38.944023,"lon":-68.183674,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1191","desc":"NV1191","lat":-38.952584,"lon":-68.173149,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1100","desc":"NV1100","lat":-38.946053,"lon":-68.057388,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1101","desc":"NV1101","lat":-38.944472,"lon":-68.057576,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1103","desc":"NV1103","lat":-38.945368,"lon":-68.056130,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1102","desc":"NV1102","lat":-38.944522,"lon":-68.057589,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1105","desc":"NV1105","lat":-38.945096,"lon":-68.057502,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1107","desc":"NV1107","lat":-38.954399,"lon":-68.056151,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1108","desc":"NV1108","lat":-38.955075,"lon":-68.056623,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1110","desc":"NV1110","lat":-38.958181,"lon":-68.061033,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1112","desc":"NV1112","lat":-38.958190,"lon":-68.063844,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1118","desc":"NV1118","lat":-38.959192,"lon":-68.101081,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1119","desc":"NV1119","lat":-38.959146,"lon":-68.106864,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1120","desc":"NV1120","lat":-38.959150,"lon":-68.117195,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1142","desc":"NV1142","lat":-38.957599,"lon":-68.140949,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1155","desc":"NV1155","lat":-38.944520,"lon":-68.204068,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1156","desc":"NV1156","lat":-38.944470,"lon":-68.208917,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1158","desc":"NV1158","lat":-38.944479,"lon":-68.214572,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1170","desc":"NV1170","lat":-38.944476,"lon":-68.220479,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1177","desc":"NV1177","lat":-38.944425,"lon":-68.224737,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1180","desc":"NV1180","lat":-38.944388,"lon":-68.225703,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1210","desc":"NV1210","lat":-38.935223,"lon":-68.225661,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1220","desc":"NV1220","lat":-38.935148,"lon":-68.232008,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1250","desc":"NV1250","lat":-38.935091,"lon":-68.233589,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1270","desc":"NV1270","lat":-38.935158,"lon":-68.236422,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"NV1244","desc":"NV1244","lat":-38.930301,"lon":-68.252027,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 009","desc":"Alcorta y Candelaria","lat":-38.958214,"lon":-68.077601,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 010","desc":"Alcorta y Soldado Desconocido","lat":-38.958216,"lon":-68.074746,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 012","desc":"Alcorta y Mango","lat":-38.958208,"lon":-68.071608,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 013","desc":"Alcorta y Nordestrom","lat":-38.958232,"lon":-68.069320,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 014","desc":"Alcorta y Lainez","lat":-38.958245,"lon":-68.066568,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"},
      {"id":"50A B R 015","desc":"Anaya y Kumenia","lat":-38.958600,"lon":-68.084252,"cod":1013,"linea":"50A","sentido":"Hacia Plottier"}
    ];

    const RUTAS_GEO = {};
    for (let l in TRAZAS_RAW) {
      RUTAS_GEO[l] = {};
      for (let s in TRAZAS_RAW[l]) {
        RUTAS_GEO[l][s] = TRAZAS_RAW[l][s].map(p => mercatorALatLon(p[0], p[1]));
      }
    }

    let map;
    let capaRuta = null;
    let capaParadas = null;
    let marcadores = {};
    let paradasVisibles = true;
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

      // Al cambiar zoom, oculta paradas si está muy alejado para no saturar
      map.on('zoomend', () => {
        if (map.getZoom() < 13 && paradasVisibles) {
          capaParadas.clearLayers();
          document.getElementById('btn-toggle-stops').innerText = "🚏 Paradas (Zoom alejado)";
        } else if (map.getZoom() >= 13 && paradasVisibles && capaParadas.getLayers().length === 0) {
          dibujarParadasEnMapa();
          document.getElementById('btn-toggle-stops').innerText = "🚏 Ocultar Paradas";
        }
      });
    }

    function dibujarParadasEnMapa() {
      capaParadas.clearLayers();
      PARADAS_OFICIALES.forEach(p => {
        const marker = L.circleMarker([p.lat, p.lon], {
          radius: 5,
          color: '#181825',
          weight: 1.5,
          fillColor: (p.sentido === 'Hacia Neuquén') ? '#FAB387' : '#A6E3A1',
          fillOpacity: 0.95
        });

        // Popup interactivo que consulta en vivo a Indalo al hacer clic
        const contenidoInicial = `
          <div style="font-family: sans-serif; font-size: 13px; line-height: 1.4; min-width: 175px;">
            <strong style="color: #111; font-size: 14px;">🚏 Parada ${p.id}</strong><br>
            <span style="color: #666; font-size: 12px;">${p.desc}</span><br>
            <span style="color: #888; font-size: 11px;">Línea ${p.linea} - ${p.sentido}</span>
            <hr style="margin: 7px 0; border: none; border-top: 1px solid #E0E0E0;">
            <div id="arribo-stop-${p.id}" style="color: #555; font-size: 12px;">
              <span>Consultando arribos en vivo... ⏳</span>
            </div>
          </div>
        `;

        marker.bindPopup(contenidoInicial);
        marker.on('click', () => {
          pedirArriboDeParada(p.id, p.cod, p.linea);
        });

        capaParadas.addLayer(marker);
      });
    }

    async function pedirArriboDeParada(idParada, codLinea, linea) {
      const contenedor = document.getElementById(`arribo-stop-${idParada}`);
      if (!contenedor) return;

      try {
        const res = await fetch(`/api/parada?id=${encodeURIComponent(idParada)}&cod=${codLinea}&linea=${linea}`);
        const data = await res.json();

        if (!data.arribos || data.arribos.length === 0) {
          contenedor.innerHTML = `<span style="color: #888; font-style: italic;">Sin colectivos próximos en los próximos 45 min.</span>`;
        } else {
          let htmlArribos = '';
          data.arribos.forEach(a => {
            const btnUbicar = (a.lat && a.lon) 
              ? `<button style="background: #181825; color: #89B4FA; border: 1px solid #313244; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; cursor: pointer; margin-left: 6px;" onclick="centrarEn(${a.lat}, ${a.lon}, '${linea}', '${a.sentido_code}')">Ubicar coche</button>`
              : '';

            htmlArribos += `
              <div style="margin-top: 4px;">
                <span style="font-weight: 700; color: #2E7D32;">⏱️ ${a.tiempo}</span>
                <span style="font-size: 11px; color: #555;">(${a.ramal})</span>
                ${btnUbicar}
              </div>
            `;
          });
          contenedor.innerHTML = htmlArribos;

          // Si vino algún coche con GPS, actualiza la flota global de inmediato
          if (data.buses && data.buses.length > 0) {
            actualizarMapa(data.buses);
          }
        }
      } catch (err) {
        contenedor.innerHTML = `<span style="color: #C62828;">Error consultando parada. Reintente.</span>`;
      }
    }

    function alternarParadas() {
      paradasVisibles = !paradasVisibles;
      const btn = document.getElementById('btn-toggle-stops');
      if (paradasVisibles) {
        dibujarParadasEnMapa();
        btn.innerText = "🚏 Ocultar Paradas";
      } else {
        capaParadas.clearLayers();
        btn.innerText = "🚏 Ver Paradas";
      }
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea]) return;

      const sentidoActivo = sentidoCode || "HACIA_NEUQUEN";
      const sentidoSecundario = (sentidoActivo === "HACIA_NEUQUEN") ? "HACIA_PLOTTIER" : "HACIA_NEUQUEN";

      const colorBase = (linea === "50A") ? "#2ECC71" : "#3B82F6";
      const colorSec = (linea === "50A") ? "#16A085" : "#1D4ED8";

      if (RUTAS_GEO[linea][sentidoSecundario]) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoSecundario], {
          color: colorSec,
          weight: 3.5,
          opacity: 0.6,
          lineJoin: 'round'
        }));
      }

      if (RUTAS_GEO[linea][sentidoActivo]) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoActivo], {
          color: colorBase,
          weight: 6,
          opacity: 0.95,
          lineJoin: 'round'
        }));
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
        const res = await fetch('/api/arribos');
        const data = await res.json();
        
        renderTarjetas(data.items);
        actualizarMapa(data.buses);

        status.innerText = "Actualizado: " + data.hora;
        iniciarCooldown(4);
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
        
        let claseCss = (b.linea === "50A") ? "bus-marker-50a" : "bus-marker-50b";
        if (esPerdido) claseCss = "bus-marker-lost";

        const iconoHtml = `<div class="bus-marker ${claseCss}">${esPerdido ? '⚠️' : '🚌'} ${b.linea}</div>`;
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

        if (marcadores[b.id]) {
          marcadores[b.id].setLatLng([b.lat, b.lon]);
          marcadores[b.id].setIcon(icon);
          marcadores[b.id].getPopup().setContent(contenidoPopup);
        } else {
          const marker = L.marker([b.lat, b.lon], { icon: icon });
          marker.bindPopup(contenidoPopup);
          marker.on('click', () => {
            mostrarRuta(b.linea, b.sentido_code);
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

        let tagClase = (item.linea === "50A") ? "line-50a" : "line-50b";

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
              ? `<button class="btn-action" onclick="centrarEn(${c.lat}, ${c.lon}, '${item.linea}', '${c.sentido_code}')">Ver en Mapa</button>` 
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

    setInterval(pedirDatos, 25000);
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

# Endpoint interactivo bajo demanda: se ejecuta cuando el usuario toca cualquier parada en el mapa
@app.route('/api/parada')
def api_parada_click():
    parada_id = request.args.get('id')
    cod_linea = request.args.get('cod', '1013')
    linea = request.args.get('linea', '50A')

    if not parada_id:
        return jsonify({"error": "Falta parada"}), 400

    ahora = time.time()
    cache_key = f"{parada_id}_{cod_linea}"

    if cache_key in cache_paradas_click:
        ts, datos_guardados = cache_paradas_click[cache_key]
        if (ahora - ts) < 12:
            return jsonify(datos_guardados)

    arribos_raw = consultar_arribos_api(parada_id, cod_linea)
    arribos_limpios = []
    buses_nuevos = []

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
                f_lat, f_lon = None, None

        arribos_limpios.append({
            "tiempo": tiempo,
            "ramal": ramal,
            "sentido": sentido,
            "sentido_code": sentido_code,
            "lat": f_lat,
            "lon": f_lon
        })

        # Alimentar la flota global con lo descubierto al hacer click
        if f_lat and f_lon:
            actualizar_coche_en_memoria(linea, ramal, sentido, sentido_code, None, f_lat, f_lon, ahora)

    respuesta = {
        "arribos": arribos_limpios,
        "buses": serializar_flota(ahora)
    }
    cache_paradas_click[cache_key] = (ahora, respuesta)
    return jsonify(respuesta)

# Endpoint principal de sincronización periódica
@app.route('/api/arribos')
def api_arribos():
    global flota_memoria, cabeceras_memoria, ultima_hora_sync, ultimo_escaneo_ts
    ahora = time.time()

    if (ahora - ultimo_escaneo_ts) < CACHE_TTL and cabeceras_memoria:
        return jsonify({
            "hora": ultima_hora_sync,
            "items": list(cabeceras_memoria.values()),
            "buses": serializar_flota(ahora),
            "from_cache": True
        })

    consultas_ok = 0
    buses_leidos_ronda = []

    for item in CONSULTAS_RADAR:
        arribos_raw = consultar_arribos_api(item["parada"], item["cod"])
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
                    f_lat, f_lon = None, None

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
            clave_cab = (item["parada"], item["linea"])
            cabeceras_memoria[clave_cab] = {
                "seccion": "CABECERA",
                "parada": item["parada"],
                "linea": item["linea"],
                "arribos": arribos_limpios
            }

        consultas_ok += 1
        time.sleep(0.3)

    # 1. Deduplicación intra-ronda de alta precisión (45 metros)
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

    # 2. Seguimiento de ruta (900m direccionales sin colisiones opuestas)
    for b in buses_unicos_ronda:
        actualizar_coche_en_memoria(b["linea"], b["ramal"], b["sentido"], b["sentido_code"], 
                                     b["tiempo"] if b["es_cabecera"] else None, b["lat"], b["lon"], ahora)

    flota_memoria = {k: v for k, v in flota_memoria.items() if (ahora - v["last_seen"]) < TIEMPO_EXPIRAR}

    if consultas_ok > 0 or not cabeceras_memoria:
        ultima_hora_sync = obtener_hora_arg()
        ultimo_escaneo_ts = ahora

    return jsonify({
        "hora": ultima_hora_sync,
        "items": list(cabeceras_memoria.values()),
        "buses": serializar_flota(ahora),
        "from_cache": False
    })

def actualizar_coche_en_memoria(linea, ramal, sentido, sentido_code, tiempo_cab, lat, lon, ahora):
    bus_match_id = None
    menor_distancia = 0.90

    for bus_id, datos in flota_memoria.items():
        if datos["linea"] == linea and datos["sentido_code"] == sentido_code:
            dist = calcular_distancia(datos["lat"], datos["lon"], lat, lon)
            if dist < menor_distancia:
                menor_distancia = dist
                bus_match_id = bus_id

    if bus_match_id:
        flota_memoria[bus_match_id]["lat"] = lat
        flota_memoria[bus_match_id]["lon"] = lon
        flota_memoria[bus_match_id]["last_seen"] = ahora
        flota_memoria[bus_match_id]["ramal"] = ramal
        flota_memoria[bus_match_id]["sentido"] = sentido
        flota_memoria[bus_match_id]["sentido_code"] = sentido_code
        if tiempo_cab:
            flota_memoria[bus_match_id]["tiempo_cabecera"] = tiempo_cab
    else:
        nuevo_id = f"{linea}_{sentido_code}_{round(lat, 3)}_{round(lon, 3)}"
        flota_memoria[nuevo_id] = {
            "id": nuevo_id,
            "linea": linea,
            "ramal": ramal,
            "sentido": sentido,
            "sentido_code": sentido_code,
            "tiempo_cabecera": tiempo_cab,
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
