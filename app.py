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

PARADAS_INTERMEDIAS_ROTATIVAS = [
    {"parada": "NV1058", "linea": "50B", "cod": "1014"},
    {"parada": "NV1032", "linea": "50A", "cod": "1013"},
    {"parada": "NV1244", "linea": "50B", "cod": "1014"},
    {"parada": "NV1244", "linea": "50A", "cod": "1013"},
    {"parada": "NV1032", "linea": "50R", "cod": "1015"},
]
indice_rotativo = 0

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
})
csrf_token = None

CACHE_TTL = 15
TIEMPO_DEAD_RECKONING = 60
TIEMPO_EXPIRAR = 360

flota_memoria = {}
cabeceras_memoria = {
    ("NV2000", "50B"): {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "arribos": []},
    ("NV1014", "50A"): {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "arribos": []},
}
ultima_hora_sync = "--:--:--"
ultimo_escaneo_ts = 0


def obtener_hora_arg():
    tz_arg = timezone(timedelta(hours=-3))
    return datetime.now(tz_arg).strftime("%H:%M:%S")


def calcular_distancia(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2) * 111.0


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
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-CE85R9NET5"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-CE85R9NET5');
  </script>

  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Líneas 50A / 50B / 50R - Monitoreo Profesional</title>
  
  <meta name="theme-color" content="#0F111A">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #0F111A; color: #CDD6F4; padding: 14px 12px 90px; }
    
    header { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-end; }
    h1 { font-size: 20px; color: #89B4FA; font-weight: 800; letter-spacing: -0.3px; }
    .sub { font-size: 12px; color: #A6ADC8; }

    #map-container {
      position: relative;
      margin-bottom: 16px;
      border-radius: 16px;
      overflow: hidden;
      border: 1px solid #23273A;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    }
    #map {
      height: 360px;
      width: 100%;
      background: #0B0D13;
    }

    .hud-badge {
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 1000;
      background: rgba(15, 17, 26, 0.88);
      backdrop-filter: blur(8px);
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 11px;
      color: #CDD6F4;
      border: 1px solid #313244;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .hud-dot { width: 7px; height: 7px; border-radius: 50%; background: #A6E3A1; box-shadow: 0 0 6px #A6E3A1; }

    .map-btn-group {
      position: absolute;
      bottom: 12px;
      right: 12px;
      z-index: 1000;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .map-ctrl-btn {
      background: rgba(15, 17, 26, 0.9);
      backdrop-filter: blur(8px);
      border: 1px solid #313244;
      color: #CDD6F4;
      width: 38px;
      height: 38px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 4px 10px rgba(0,0,0,0.4);
      font-size: 15px;
    }
    .btn-clear-route {
      position: absolute;
      bottom: 12px;
      left: 12px;
      z-index: 1000;
      background: rgba(243, 139, 168, 0.15);
      border: 1px solid #F38BA8;
      color: #F38BA8;
      font-size: 11px;
      font-weight: 700;
      padding: 6px 12px;
      border-radius: 20px;
      cursor: pointer;
      display: none;
    }

    /* Marcador Uber de Usuario */
    .user-beacon {
      position: relative;
      width: 22px;
      height: 22px;
    }
    .user-beacon-core {
      position: absolute;
      top: 5px;
      left: 5px;
      width: 12px;
      height: 12px;
      background: #3B82F6;
      border: 2px solid #FFFFFF;
      border-radius: 50%;
      box-shadow: 0 0 10px rgba(59, 130, 246, 0.8);
      z-index: 2;
    }
    .user-beacon-pulse {
      position: absolute;
      width: 22px;
      height: 22px;
      background: rgba(59, 130, 246, 0.35);
      border-radius: 50%;
      animation: uber-pulse 2s infinite ease-out;
      z-index: 1;
    }
    @keyframes uber-pulse {
      0% { transform: scale(0.6); opacity: 1; }
      100% { transform: scale(2.2); opacity: 0; }
    }

    /* Vehículo Estilo Uber / Píldora de Navegación */
    .uber-puck {
      position: relative;
      width: 72px;
      height: 28px;
      pointer-events: auto;
    }
    .puck-body {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 4px;
      padding: 2px 7px;
      border-radius: 20px;
      background: #181825;
      border: 1.5px solid #89B4FA;
      box-shadow: 0 4px 12px rgba(0,0,0,0.6);
      color: #FFF;
      font-size: 11px;
      font-weight: 800;
      height: 100%;
    }
    .puck-arrow {
      font-size: 10px;
      display: inline-block;
      transition: transform 0.5s ease;
      color: #89B4FA;
    }
    .puck-50a { border-color: #A6E3A1; color: #A6E3A1; }
    .puck-50a .puck-arrow { color: #A6E3A1; }
    .puck-50b { border-color: #89B4FA; color: #89B4FA; }
    .puck-50b .puck-arrow { color: #89B4FA; }
    .puck-50r { border-color: #FAB387; color: #FAB387; }
    .puck-50r .puck-arrow { color: #FAB387; }

    .puck-dr {
      border-style: dashed !important;
      border-color: #F9E2AF !important;
      background: #201C16 !important;
      color: #F9E2AF !important;
    }
    .puck-dr .puck-arrow { color: #F9E2AF !important; }

    .section-title { font-size: 13px; color: #A6ADC8; text-transform: uppercase; letter-spacing: 0.8px; margin: 16px 0 8px; font-weight: 700; }
    .card { background: #181825; border: 1px solid #23273A; border-radius: 14px; padding: 12px 14px; margin-bottom: 8px; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .line-tag { font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 6px; background: #23273A; }
    .stop-tag { font-size: 11px; color: #6C7086; }
    
    .arrival-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-top: 1px solid #1E1E2E; }
    .arrival-row:first-of-type { border-top: none; }
    .time-val { font-size: 14px; font-weight: 800; color: #A6E3A1; }
    .dist-user { font-size: 11px; color: #89B4FA; font-weight: 600; margin-top: 2px; }

    .btn-action { background: #23273A; color: #CDD6F4; border: 1px solid #313244; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 8px; cursor: pointer; }

    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(15, 17, 26, 0.95); backdrop-filter: blur(12px); padding: 10px 14px; border-top: 1px solid #23273A; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #3B82F6; color: #FFF; border: none; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 10px; cursor: pointer; }
    .btn-refresh:disabled { opacity: 0.5; }
    .status-text { font-size: 11px; color: #A6ADC8; text-align: right; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Red Metropolitana</h1>
      <p class="sub">Telemetría y navegación vehicular continua</p>
    </div>
  </header>

  <div id="map-container">
    <div class="hud-badge">
      <span class="hud-dot"></span>
      <span id="bus-count">Conectando telemetría...</span>
    </div>
    <div class="map-btn-group">
      <button class="map-ctrl-btn" onclick="centrarEnUsuario()" title="Mi ubicación">📍</button>
    </div>
    <button class="btn-clear-route" id="btn-clear" onclick="limpiarRuta()">✕ Quitar ruta</button>
    <div id="map"></div>
  </div>

  <div id="contenido">Obteniendo arribos de red...</div>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-text">
      <div id="status">Sincronizando...</div>
      <div style="font-size: 10px; color: #A6E3A1;">Filtro Dead-Reckoning Activo</div>
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

    const RUTAS_GEO = {};
    for (let l in TRAZAS_RAW) {
      RUTAS_GEO[l] = {};
      for (let s in TRAZAS_RAW[l]) {
        RUTAS_GEO[l][s] = TRAZAS_RAW[l][s].map(p => mercatorALatLon(p[0], p[1]));
      }
    }

    let map;
    let capaRuta = null;
    let marcadores = {};
    let estadoVehiculos = {};
    let usuarioMarker = null;
    let usuarioPos = null;

    function distanciaMetros(lat1, lon1, lat2, lon2) {
      const R = 6371000;
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon/2) * Math.sin(dLon/2);
      return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    }

    function calcularRumbo(lat1, lon1, lat2, lon2) {
      const y = Math.sin((lon2 - lon1) * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180);
      const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180) -
                Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos((lon2 - lon1) * Math.PI / 180);
      let brng = Math.atan2(y, x) * 180 / Math.PI;
      return (brng + 360) % 360;
    }

    // Map Matching: Proyección ortogonal a la calzada más cercana
    function snapATraza(lat, lon, linea, sentidoCode) {
      const traza = RUTAS_GEO[linea] && RUTAS_GEO[linea][sentidoCode];
      if (!traza || traza.length < 2) return { lat, lon, bearing: 0 };

      let minD = Infinity;
      let snapP = [lat, lon];
      let bearing = 0;

      for (let i = 0; i < traza.length - 1; i++) {
        const p1 = traza[i];
        const p2 = traza[i+1];
        const d = distanciaMetros(lat, lon, p1[0], p1[1]);
        if (d < minD && d < 180) { // Tolerancia máxima 180m de desvío
          minD = d;
          snapP = p1;
          bearing = calcularRumbo(p1[0], p1[1], p2[0], p2[1]);
        }
      }
      return { lat: snapP[0], lon: snapP[1], bearing };
    }

    function initMap() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.16], 13);
      L.control.zoom({ position: 'topright' }).addTo(map);

      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        attribution: '&copy; CartoDB &copy; OpenStreetMap'
      }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);

      // Rastreo en vivo del usuario estilo Uber
      if ("geolocation" in navigator) {
        navigator.geolocation.watchPosition(pos => {
          usuarioPos = [pos.coords.latitude, pos.coords.longitude];
          const beaconHtml = `
            <div class="user-beacon">
              <div class="user-beacon-pulse"></div>
              <div class="user-beacon-core"></div>
            </div>
          `;
          const beaconIcon = L.divIcon({ className: '', html: beaconHtml, iconSize: [22, 22], iconAnchor: [11, 11] });
          if (!usuarioMarker) {
            usuarioMarker = L.marker(usuarioPos, { icon: beaconIcon, zIndexOffset: 2000 }).addTo(map);
          } else {
            usuarioMarker.setLatLng(usuarioPos);
          }
        }, () => {}, { enableHighAccuracy: true });
      }

      // Loop de animación a 60 FPS (Lerp e interpolación)
      requestAnimationFrame(motorAnimacion);
    }

    function centrarEnUsuario() {
      if (usuarioPos) {
        map.setView(usuarioPos, 15, { animate: true });
      } else {
        alert("Obteniendo señal satelital de tu dispositivo...");
      }
    }

    function motorAnimacion() {
      const step = 0.08; // Coeficiente de suavizado
      for (let id in estadoVehiculos) {
        const v = estadoVehiculos[id];
        if (!v.marker) continue;

        // Interpolación lineal lat/lon
        v.latActual += (v.latTarget - v.latActual) * step;
        v.lonActual += (v.lonTarget - v.lonActual) * step;
        v.marker.setLatLng([v.latActual, v.lonActual]);

        // Rotación de flecha indicadora
        const el = document.getElementById(`arrow-${id}`);
        if (el && v.bearingTarget !== undefined) {
          el.style.transform = `rotate(${v.bearingTarget}deg)`;
        }
      }
      requestAnimationFrame(motorAnimacion);
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea]) return;

      const sentidoActivo = sentidoCode || "HACIA_NEUQUEN";
      const sentidoSecundario = (sentidoActivo === "HACIA_NEUQUEN") ? "HACIA_PLOTTIER" : "HACIA_NEUQUEN";
      const colorBase = (linea === "50A") ? "#2ECC71" : "#3B82F6";

      if (RUTAS_GEO[linea][sentidoSecundario]) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoSecundario], {
          color: "#45475A",
          weight: 3,
          opacity: 0.5
        }));
      }

      if (RUTAS_GEO[linea][sentidoActivo]) {
        capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoActivo], {
          color: colorBase,
          weight: 5,
          opacity: 0.95
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

    async function pedirDatos() {
      const status = document.getElementById('status');
      try {
        const res = await fetch('/api/arribos');
        const data = await res.json();
        renderTarjetas(data.items);
        actualizarFlota(data.buses);
        status.innerText = "Sincronizado: " + data.hora;
      } catch (err) {
        status.innerText = "Reintentando conexión...";
      }
    }

    function actualizarFlota(buses) {
      const countLabel = document.getElementById('bus-count');
      if (!buses || buses.length === 0) {
        countLabel.innerText = "Sin unidades en línea";
        return;
      }

      const activos = buses.filter(b => b.estado === 'activo').length;
      const estimados = buses.filter(b => b.estado === 'estimado').length;
      countLabel.innerText = `${activos} GPS activo${estimados > 0 ? ' | ' + estimados + ' estimados' : ''}`;

      const idsServer = new Set();

      buses.forEach(b => {
        if (!b.lat || !b.lon) return;
        idsServer.add(b.id);

        const snapped = snapATraza(b.lat, b.lon, b.linea, b.sentido_code);
        const esEstimado = (b.estado === 'estimado');

        let claseLinea = "puck-50b";
        if (b.linea === "50A") claseLinea = "puck-50a";
        else if (b.linea === "50R") claseLinea = "puck-50r";
        if (esEstimado) claseLinea += " puck-dr";

        let distUsuarioTxt = "";
        if (usuarioPos) {
          const dM = Math.round(distanciaMetros(usuarioPos[0], usuarioPos[1], snapped.lat, snapped.lon));
          distUsuarioTxt = (dM < 1000) ? ` • a ${dM} m de vos` : ` • a ${(dM/1000).toFixed(1)} km`;
        }

        const htmlPuck = `
          <div class="uber-puck">
            <div class="puck-body ${claseLinea}">
              <span class="puck-arrow" id="arrow-${b.id}">➤</span>
              <span>${b.linea}</span>
              <span style="font-size:9px; opacity:0.8">${esEstimado ? 'EST' : 'GPS'}</span>
            </div>
          </div>
        `;

        const icon = L.divIcon({
          className: '',
          html: htmlPuck,
          iconSize: [72, 28],
          iconAnchor: [36, 14]
        });

        const sentidoTxt = (b.sentido_code === 'HACIA_NEUQUEN') ? '🟠 Hacia Neuquén' : '🟢 Hacia Plottier';
        const popupHtml = `
          <div style="font-family: sans-serif; font-size: 13px; line-height: 1.4; color: #111;">
            <strong>Línea ${b.linea}</strong> (${b.ramal})<br>
            <span style="font-weight: 700;">${sentidoTxt}</span><br>
            <small style="color: #666;">Estado: ${esEstimado ? 'Navegación estimada (sin señal directa)' : 'Transmisión satelital activa'}</small>
            ${b.tiempo_cabecera ? `<div style="color: #059669; font-weight: bold; margin-top: 4px;">⏱️ Arribo: ${b.tiempo_cabecera}</div>` : ''}
          </div>
        `;

        if (estadoVehiculos[b.id]) {
          // El coche ya existe: se actualiza el target para animación fluida continua
          estadoVehiculos[b.id].latTarget = snapped.lat;
          estadoVehiculos[b.id].lonTarget = snapped.lon;
          estadoVehiculos[b.id].bearingTarget = snapped.bearing;
          estadoVehiculos[b.id].marker.setIcon(icon);
          estadoVehiculos[b.id].marker.getPopup().setContent(popupHtml);
        } else {
          // Alta de nueva unidad con coordenadas suavizadas
          const marker = L.marker([snapped.lat, snapped.lon], { icon: icon }).addTo(map);
          marker.bindPopup(popupHtml);
          marker.on('click', () => mostrarRuta(b.linea, b.sentido_code));

          estadoVehiculos[b.id] = {
            id: b.id,
            marker: marker,
            latActual: snapped.lat,
            lonActual: snapped.lon,
            latTarget: snapped.lat,
            lonTarget: snapped.lon,
            bearingTarget: snapped.bearing
          };
        }
      });

      // Eliminación limpia de coches obsoletos
      for (let id in estadoVehiculos) {
        if (!idsServer.has(id)) {
          map.removeLayer(estadoVehiculos[id].marker);
          delete estadoVehiculos[id];
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

        html += `<div class="card">
          <div class="card-header">
            <span class="line-tag">Línea ${item.linea}</span>
            <span class="stop-tag">Cabecera ${item.parada}</span>
          </div>`;

        if (!item.arribos || item.arribos.length === 0) {
          html += `<div style="font-size:12px; color:#6C7086; padding: 4px 0;">Sin salidas registradas en este momento</div>`;
        } else {
          item.arribos.forEach(c => {
            const tienePos = (c.lat && c.lon);
            let distTxt = "";
            if (tienePos && usuarioPos) {
              const dM = Math.round(distanciaMetros(usuarioPos[0], usuarioPos[1], c.lat, c.lon));
              distTxt = `<div class="dist-user">📍 A ${(dM < 1000) ? dM + ' m' : (dM/1000).toFixed(1) + ' km'} de tu ubicación</div>`;
            }

            html += `<div class="arrival-row">
              <div>
                <div style="font-size: 13px; font-weight: 600;">${c.ramal} <span style="font-size: 11px; opacity: 0.8">(${c.sentido})</span></div>
                <div style="font-size: 12px; color: #A6ADC8;">Próximo arribo: <span class="time-val">${c.tiempo}</span></div>
                ${distTxt}
              </div>
              <div>
                ${tienePos ? `<button class="btn-action" onclick="centrarEn(${c.lat}, ${c.lon}, '${item.linea}', '${c.sentido_code}')">Rastrear</button>` : ''}
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


@app.route('/api/arribos')
def api_arribos():
    global flota_memoria, cabeceras_memoria, ultima_hora_sync, ultimo_escaneo_ts, indice_rotativo
    ahora = time.time()

    if (ahora - ultimo_escaneo_ts) < CACHE_TTL and cabeceras_memoria:
        return jsonify({
            "hora": ultima_hora_sync,
            "items": list(cabeceras_memoria.values()),
            "buses": serializar_flota(ahora),
            "from_cache": True
        })

    consultas_a_ejecutar = [
        {"seccion": "CABECERA", "parada": "NV2000", "linea": "50B", "cod": "1014", "mostrar": True},
        {"seccion": "CABECERA", "parada": "NV1014", "linea": "50A", "cod": "1013", "mostrar": True},
    ]

    if PARADAS_INTERMEDIAS_ROTATIVAS:
        intermedia = PARADAS_INTERMEDIAS_ROTATIVAS[indice_rotativo]
        consultas_a_ejecutar.append({**intermedia, "seccion": "BARRIDO", "mostrar": False})
        indice_rotativo = (indice_rotativo + 1) % len(PARADAS_INTERMEDIAS_ROTATIVAS)

    consultas_ok = 0
    buses_leidos_ronda = []

    for item in consultas_a_ejecutar:
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
        except Exception:
            pass

    # Deduplicación de precisión (45 metros)
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

    # Motor de seguimiento satelital
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

    # Depuración por expiración real (6 minutos sin contacto satelital ni estimado)
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


def serializar_flota(ahora):
    lista = []
    for bus_id, datos in flota_memoria.items():
        inactivo = ahora - datos["last_seen"]
        # Dead Reckoning: si pasaron más de 60s sin reporte, pasa a navegación estimada
        estado = "estimado" if inactivo > TIEMPO_DEAD_RECKONING else "activo"
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
