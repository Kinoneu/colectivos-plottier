import math

CABECERAS_GEO = [
    (-38.9314, -68.2494, "Cabecera Plottier Norte"),
    (-38.9345, -68.2585, "Cabecera Casa de Té"),
    (-38.9302, -68.2585, "Cabecera Aristóbulo del Valle"),
    (-38.9607, -68.2491, "Cabecera Plottier Sur"),
    (-38.9645, -68.2433, "Cabecera Zabaleta"),
    (-38.9562, -68.2176, "Terminal ETOP Plottier"),
    (-38.9561, -68.3385, "Cabecera Las Lilas / 50R"),
    (-38.9840, -68.3494, "Cabecera B° Las Perlas"),
    (-38.9822, -68.3070, "Cabecera Las Perlas Este"),
    (-38.9461, -68.0575, "Cabecera Neuquén Centro"),
    (-38.9571, -68.0562, "Cabecera Neuquén Parque Central"),
    (-38.9539, -68.2324, "Estación Plottier (Tren del Valle)"),
    (-38.9563, -68.0591, "Estación Neuquén Central (Tren)"),
    (-38.9392, -67.9975, "Estación Cipolletti (Tren)")
]

PARADAS_RADAR = [
    ("NV4120", "1013", "50A"),
    ("NV1012", "1013", "50A"),
    ("NV8039", "1013", "50A"),
    ("NV1027", "1013", "50A"),
    ("NV4120", "1014", "50B"),
    ("NV1012", "1014", "50B"),
    ("NV1173", "1014", "50B"),
    ("NV1027", "1014", "50B"),
    ("NV 4998", "1015", "50R"),
    ("NV6001", "1015", "50R"),
    ("NV5019", "1015", "50R"),
    ("NV8064", "1109", "URBANO"),
    ("51 00001", "1109", "URBANO"),
    ("5200001", "1079", "52 CENTRO"),
    ("5200047", "1079", "52 CENTRO"),
    ("5200001", "1080", "52 UNION"),
    ("5200047", "1080", "52 UNION")
]

# Trazado ferroviario oficial del Tren del Valle (Plottier <-> Neuquén Central <-> Cipolletti)
TRAZA_VIAL_TREN = [
    [-38.953950, -68.232450], # Estación Plottier
    [-38.954250, -68.225800], # Cruce Av. San Martín
    [-38.954450, -68.218500], # Altura ETOP
    [-38.954800, -68.206000], # Altura Sapag
    [-38.955020, -68.196900], # Apeadero Constituyentes
    [-38.955080, -68.192400], # Altura EPEA No 2
    [-38.955120, -68.184500], # Altura Piscicultura
    [-38.955150, -68.177750], # Apeadero Barrio Unión
    [-38.955550, -68.167650], # Cruce Río Colorado
    [-38.956250, -68.159750], # Apeadero Aeropuerto
    [-38.956800, -68.153800], # Valentina Norte Rural
    [-38.957150, -68.148150], # Apeadero El Cholar
    [-38.957350, -68.139800], # Apeadero ETON
    [-38.957550, -68.128000], # Solalique / Crouzeilles
    [-38.958200, -68.117200], # Bejarano
    [-38.958400, -68.106500], # Chrestia
    [-38.958500, -68.093500], # Gatica
    [-38.958550, -68.078950], # Apeadero Ignacio Rivas
    [-38.958000, -68.066500], # Laínez
    [-38.956300, -68.059100], # Estación Neuquén Central
    [-38.956200, -68.051000], # Parque Central Este
    [-38.955800, -68.040000], # Bahía Blanca / Santa Fe
    [-38.954500, -68.027500], # Aproximación Río Neuquén
    [-38.947800, -68.015500], # Puente Ferroviario Neuquén-Cipolletti
    [-38.942500, -68.004500], # Ingreso Ferroviario Cipolletti
    [-38.939200, -67.997500]  # Estación Cipolletti
]

TRAZA_TREN_GEO = {
    "HACIA_NEUQUEN": TRAZA_VIAL_TREN,
    "HACIA_PLOTTIER": list(reversed(TRAZA_VIAL_TREN))
}

# Puntos de control oficiales (11 de colectivos + 9 estaciones del Tren del Valle)
PUNTOS_CONTROL_OFICIALES = [
    {
        "key": "LOTEO_SOCIAL",
        "nombreOficial": "Loteo Social (Cabecera)",
        "lat": -38.930393, "lon": -68.252000, "radio_mts": 150,
        "cols50A": [{"idx": 0, "offset": 0, "label": "Salida hacia Nqn"}],
        "cols50B": [{"idx": 0, "offset": 0, "label": "Salida hacia Nqn"}],
        "cols50R": [], "colsTREN": []
    },
    {
        "key": "SAN_MARTIN_TRABAJO",
        "nombreOficial": "San Martín y Av. del Trabajo",
        "lat": -38.944473, "lon": -68.225598, "radio_mts": 160,
        "cols50A": [{"idx": 1, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 7, "offset": 4, "label": "Regreso a Cabecera"}],
        "cols50B": [{"idx": 0, "offset": 8, "label": "Hacia Neuquén"}, {"idx": 6, "offset": 0, "label": "Regreso a Cabecera"}],
        "cols50R": [], "colsTREN": []
    },
    {
        "key": "CASA_CULTURA",
        "nombreOficial": "Casa de la Cultura",
        "lat": -38.950627, "lon": -68.225753, "radio_mts": 130,
        "cols50A": [{"idx": 7, "offset": 0, "label": "Regreso a Plottier"}],
        "cols50B": [{"idx": 1, "offset": 0, "label": "Hacia Neuquén"}],
        "cols50R": [], "colsTREN": []
    },
    {
        "key": "AMANCAY_MUTICIAS",
        "nombreOficial": "Amancay y Las Muticias",
        "lat": -38.964520, "lon": -68.243109, "radio_mts": 140,
        "cols50A": [{"idx": 6, "offset": 0, "label": "Regreso a Plottier"}],
        "cols50B": [{"idx": 2, "offset": 0, "label": "Hacia Neuquén"}],
        "cols50R": [], "colsTREN": []
    },
    {
        "key": "RUTA22_RIAVITZ",
        "nombreOficial": "Ruta 22 y Riavitz",
        "lat": -38.956680, "lon": -68.226224, "radio_mts": 150,
        "cols50A": [{"idx": 5, "offset": 0, "label": "Regreso a Plottier"}],
        "cols50B": [{"idx": 2, "offset": 6, "label": "Hacia Neuquén"}],
        "cols50R": [{"idx": 1, "offset": -2, "label": "Hacia Neuquén"}, {"idx": 7, "offset": 2, "label": "Hacia El Mangrullo"}],
        "colsTREN": []
    },
    {
        "key": "RUTA22_ETOP",
        "nombreOficial": "Ruta 22 Altura ETOP",
        "lat": -38.955620, "lon": -68.218591, "radio_mts": 140,
        "cols50A": [{"idx": 5, "offset": -2, "label": "Regreso a Plottier"}],
        "cols50B": [{"idx": 2, "offset": 8, "label": "Hacia Neuquén"}],
        "cols50R": [{"idx": 1, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 7, "offset": 0, "label": "Hacia El Mangrullo"}],
        "colsTREN": []
    },
    {
        "key": "RIO_COLORADO_IDA",
        "nombreOficial": "Río Colorado / Altura Aeropuerto",
        "lat": -38.956568, "lon": -68.167666, "radio_mts": 230,
        "cols50A": [{"idx": 2, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 4, "offset": 0, "label": "Hacia Plottier"}],
        "cols50B": [{"idx": 3, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 5, "offset": 0, "label": "Hacia Plottier"}],
        "cols50R": [{"idx": 2, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 6, "offset": 0, "label": "Hacia Plottier"}],
        "colsTREN": []
    },
    {
        "key": "RUTA22_ETON",
        "nombreOficial": "Ruta 22 Altura ETON",
        "lat": -38.957999, "lon": -68.139772, "radio_mts": 220,
        "cols50A": [{"idx": 2, "offset": 7, "label": "Hacia Neuquén"}, {"idx": 4, "offset": -7, "label": "Hacia Plottier"}],
        "cols50B": [{"idx": 3, "offset": 7, "label": "Hacia Neuquén"}, {"idx": 5, "offset": -7, "label": "Hacia Plottier"}],
        "cols50R": [{"idx": 3, "offset": 0, "label": "Hacia Neuquén"}, {"idx": 5, "offset": 0, "label": "Hacia Plottier"}],
        "colsTREN": []
    },
    {
        "key": "SAN_JUAN_BSAS",
        "nombreOficial": "San Juan y Buenos Aires (Neuquén)",
        "lat": -38.944522, "lon": -68.057589, "radio_mts": 160,
        "cols50A": [{"idx": 3, "offset": 0, "label": "Cabecera Neuquén"}],
        "cols50B": [{"idx": 4, "offset": 0, "label": "Cabecera Neuquén"}],
        "cols50R": [], "colsTREN": []
    },
    {
        "key": "PARQUE_CENTRAL_NQN",
        "nombreOficial": "Parque Central Neuquén (50R)",
        "lat": -38.957187, "lon": -68.056286, "radio_mts": 245,
        "cols50A": [{"idx": 3, "offset": 5, "label": "Paso por Centro"}],
        "cols50B": [{"idx": 4, "offset": 5, "label": "Paso por Centro"}],
        "cols50R": [{"idx": 4, "offset": 0, "label": "Cabecera Neuquén"}],
        "colsTREN": []
    },
    {
        "key": "EL_MANGRULLO",
        "nombreOficial": "El Mangrullo (Cabecera 50R)",
        "lat": -38.983140, "lon": -68.350601, "radio_mts": 180,
        "cols50A": [], "cols50B": [],
        "cols50R": [{"idx": 0, "offset": 0, "label": "Salida hacia Nqn"}, {"idx": 8, "offset": 0, "label": "Llegada a Cabecera"}],
        "colsTREN": []
    },
    # --- ESTACIONES Y APEADEROS DEL TREN DEL VALLE ---
    {
        "key": "TREN_PLOTTIER",
        "nombreOficial": "Estación Plottier (Tren del Valle)",
        "lat": -38.953950, "lon": -68.232450, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 0, "offset": 0, "label": "Salida hacia Nqn / Cipo"}, {"idx": 16, "offset": 0, "label": "Llegada desde Nqn"}]
    },
    {
        "key": "TREN_CONSTITUYENTES",
        "nombreOficial": "Apeadero Constituyentes (Tren)",
        "lat": -38.955020, "lon": -68.196900, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 1, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 15, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_UNION",
        "nombreOficial": "Apeadero Barrio Unión (Tren)",
        "lat": -38.955150, "lon": -68.177750, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 2, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 14, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_AEROPUERTO",
        "nombreOficial": "Apeadero Aeropuerto (Tren)",
        "lat": -38.956250, "lon": -68.159750, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 3, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 13, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_CHOLAR",
        "nombreOficial": "Apeadero El Cholar (Tren)",
        "lat": -38.957150, "lon": -68.148150, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 4, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 12, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_ETON",
        "nombreOficial": "Apeadero ETON (Tren)",
        "lat": -38.957350, "lon": -68.139800, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 5, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 11, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_RIVAS",
        "nombreOficial": "Apeadero Ignacio Rivas (Tren)",
        "lat": -38.958550, "lon": -68.078950, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 6, "offset": 0, "label": "Hacia Neuquén / Cipo"}, {"idx": 10, "offset": 0, "label": "Hacia Plottier"}]
    },
    {
        "key": "TREN_NEUQUEN",
        "nombreOficial": "Estación Neuquén Central (Tren)",
        "lat": -38.956300, "lon": -68.059100, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 7, "offset": 0, "label": "Arribo / Paso Hacia Cipo"}, {"idx": 9, "offset": 0, "label": "Salida Hacia Plottier"}]
    },
    {
        "key": "TREN_CIPOLLETTI",
        "nombreOficial": "Estación Cipolletti (Tren del Valle)",
        "lat": -38.939200, "lon": -67.997500, "radio_mts": 40, "soloTren": True,
        "cols50A": [], "cols50B": [], "cols50R": [],
        "colsTREN": [{"idx": 8, "offset": 0, "label": "Cabecera Cipolletti"}]
    }
]

ORDEN_PARADAS = {
    "50A": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "SAN_MARTIN_TRABAJO", "RIO_COLORADO_IDA", "RUTA22_ETON", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "PARQUE_CENTRAL_NQN", "RUTA22_ETON", "RIO_COLORADO_IDA", "RUTA22_ETOP", "RUTA22_RIAVITZ", "AMANCAY_MUTICIAS", "CASA_CULTURA", "SAN_MARTIN_TRABAJO", "LOTEO_SOCIAL"]
    },
    "50B": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "SAN_MARTIN_TRABAJO", "CASA_CULTURA", "AMANCAY_MUTICIAS", "RUTA22_RIAVITZ", "RUTA22_ETOP", "RIO_COLORADO_IDA", "RUTA22_ETON", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "PARQUE_CENTRAL_NQN", "RUTA22_ETON", "RIO_COLORADO_IDA", "SAN_MARTIN_TRABAJO", "LOTEO_SOCIAL"]
    },
    "50R": {
        "HACIA_NEUQUEN": ["EL_MANGRULLO", "RUTA22_RIAVITZ", "RUTA22_ETOP", "RIO_COLORADO_IDA", "RUTA22_ETON", "PARQUE_CENTRAL_NQN"],
        "HACIA_PLOTTIER": ["PARQUE_CENTRAL_NQN", "RUTA22_ETON", "RIO_COLORADO_IDA", "RUTA22_ETOP", "RUTA22_RIAVITZ", "EL_MANGRULLO"]
    },
    "TREN": {
        "HACIA_NEUQUEN": ["TREN_PLOTTIER", "TREN_CONSTITUYENTES", "TREN_UNION", "TREN_AEROPUERTO", "TREN_CHOLAR", "TREN_ETON", "TREN_RIVAS", "TREN_NEUQUEN", "TREN_CIPOLLETTI"],
        "HACIA_PLOTTIER": ["TREN_CIPOLLETTI", "TREN_NEUQUEN", "TREN_RIVAS", "TREN_ETON", "TREN_CHOLAR", "TREN_AEROPUERTO", "TREN_UNION", "TREN_CONSTITUYENTES", "TREN_PLOTTIER"]
    },
    "URBANO": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "SAN_MARTIN_TRABAJO", "CASA_CULTURA", "AMANCAY_MUTICIAS", "RUTA22_ETOP"],
        "HACIA_PLOTTIER": ["RUTA22_ETOP", "AMANCAY_MUTICIAS", "CASA_CULTURA", "SAN_MARTIN_TRABAJO", "LOTEO_SOCIAL"]
    },
    "52 CENTRO": {
        "HACIA_NEUQUEN": ["RUTA22_ETOP", "RUTA22_RIAVITZ", "CASA_CULTURA", "SAN_MARTIN_TRABAJO", "RIO_COLORADO_IDA"],
        "HACIA_PLOTTIER": ["RIO_COLORADO_IDA", "SAN_MARTIN_TRABAJO", "RUTA22_ETOP"]
    },
    "52 UNION": {
        "HACIA_NEUQUEN": ["RUTA22_ETOP", "RUTA22_RIAVITZ", "CASA_CULTURA", "SAN_MARTIN_TRABAJO", "RIO_COLORADO_IDA"],
        "HACIA_PLOTTIER": ["RIO_COLORADO_IDA", "SAN_MARTIN_TRABAJO", "RUTA22_ETOP"]
    },
    "DEFAULT": {
        "HACIA_NEUQUEN": ["LOTEO_SOCIAL", "CASA_CULTURA", "RUTA22_RIAVITZ", "RUTA22_ETOP", "RIO_COLORADO_IDA", "SAN_JUAN_BSAS"],
        "HACIA_PLOTTIER": ["SAN_JUAN_BSAS", "RIO_COLORADO_IDA", "RUTA22_ETOP", "RUTA22_RIAVITZ", "CASA_CULTURA", "LOTEO_SOCIAL"]
    }
}

def distancia_mts(lat1, lon1, lat2, lon2):
    d_lat = (lat1 - lat2) * 111139.0
    d_lon = (lon1 - lon2) * 111139.0 * 0.777
    return math.sqrt(d_lat ** 2 + d_lon ** 2)

def _fusionar_linea_en_grupo(grupo, id_p, lineas):
    for lin_nom, lin_cod in lineas.items():
        if lin_nom not in grupo["lineas"]:
            grupo["lineas"][lin_nom] = {"cod": lin_cod, "parada": id_p, "ids": [id_p]}
        else:
            if id_p not in grupo["lineas"][lin_nom]["ids"]:
                if id_p.upper().startswith("NV") or id_p.upper().startswith("N"):
                    grupo["lineas"][lin_nom]["ids"].insert(0, id_p)
                else:
                    grupo["lineas"][lin_nom]["ids"].append(id_p)
                grupo["lineas"][lin_nom]["parada"] = ",".join(grupo["lineas"][lin_nom]["ids"])
    if id_p not in grupo["ids"]:
        grupo["ids"].append(id_p)

def agrupar_paradas_inteligente(paradas_raw, radio_comun_mts=35):
    """
    1) Crea primero las 11 Paradas Oficiales de Colectivos absorbiendo las líneas cercanas.
    2) Incluye las 9 Estaciones del Tren del Valle como nodos ferroviarios independientes.
    3) Agrupa el resto de las paradas comunes cada 35 metros.
    """
    grupos_oficiales = []
    estaciones_tren = []

    for pc in PUNTOS_CONTROL_OFICIALES:
        if pc.get("soloTren"):
            estaciones_tren.append([
                pc["key"],
                pc["lat"],
                pc["lon"],
                pc["nombreOficial"],
                {"TREN": {"cod": "TREN", "parada": pc["key"], "ids": [pc["key"]]}}
            ])
        else:
            grupos_oficiales.append({
                "ids": [],
                "lat": pc["lat"],
                "lon": pc["lon"],
                "desc": pc["nombreOficial"],
                "radio": pc.get("radio_mts", 140),
                "lineas": {}
            })

    restantes = []
    for p in paradas_raw:
        id_p, lat, lon, desc, lineas = p
        absorbido = False
        for go in grupos_oficiales:
            if distancia_mts(lat, lon, go["lat"], go["lon"]) <= go["radio"]:
                _fusionar_linea_en_grupo(go, id_p, lineas)
                absorbido = True
                break
        if not absorbido:
            restantes.append(p)

    grupos_comunes = []
    for p in restantes:
        id_p, lat, lon, desc, lineas = p
        unido = False
        for g in grupos_comunes:
            if distancia_mts(lat, lon, g["lat"], g["lon"]) <= radio_comun_mts:
                _fusionar_linea_en_grupo(g, id_p, lineas)
                unido = True
                break
        if not unido:
            nuevo_g = {"ids": [], "lat": lat, "lon": lon, "desc": desc, "lineas": {}}
            _fusionar_linea_en_grupo(nuevo_g, id_p, lineas)
            grupos_comunes.append(nuevo_g)

    todos = [g for g in grupos_oficiales if g["lineas"]] + grupos_comunes
    paradas_colectivo = [
        [" / ".join(g["ids"][:2]), g["lat"], g["lon"], g["desc"], g["lineas"]]
        for g in todos
    ]
    return paradas_colectivo + estaciones_tren

def sumar_minutos_str(hhmm, mins):
    partes = str(hhmm).split(":")
    total = (int(partes[0]) * 60 + int(partes[1]) + int(mins)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"

def construir_filas(especiales, salidas, deltas, fila_final=None):
    filas = list(especiales or [])
    acum = []
    c = 0
    for d in (deltas or []):
        c += int(d)
        acum.append(c)
    for sal in (salidas or []):
        filas.append([sumar_minutos_str(sal, m) for m in acum])
    if fila_final:
        filas.append(fila_final)
    return filas

PLANILLAS_OFICIALES = {
    "50A_HABIL": {
        "nombre": "50A Hábil",
        "columnas": ["Loteo Social", "San Martín y Trabajo", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "Ruta 22 y Riavitz", "Amancay y Muticias", "Casa Cultura", "Loteo Social"],
        "filas": construir_filas(
            [
                ["04:15","04:27","04:44","05:40","06:17","06:27","06:44","06:57","07:10"],
                ["04:48","05:00","05:17","06:13","06:50","07:00","07:17","07:30","07:43"],
                ["05:21","05:33","05:50","06:46","07:23","07:33","07:50","08:03","08:16"],
                ["05:54","06:06","06:23","07:19","07:56","08:06","08:23","08:36","08:49"],
                ["06:27","06:39","06:56","07:52","08:29","08:39","08:56","09:09","09:22"]
            ],
            ["07:20","07:53","08:26","08:59","09:32","10:06","10:39","11:12","11:45","12:18","12:52","13:25","13:58","14:31","15:04","15:38","16:11","16:44","17:17","17:50","18:24","18:57","19:30","20:03","20:36","21:10","21:43","22:16","22:49"],
            [0, 12, 17, 37, 37, 10, 17, 13, 13],
            ["23:22","23:34","23:51","00:28","-","-","-","-","-"]
        )
    },
    "50A_SAB": {
        "nombre": "50A Sábado",
        "columnas": ["Loteo Social", "San Martín y Trabajo", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "Ruta 22 y Riavitz", "Amancay y Muticias", "Casa Cultura", "Loteo Social"],
        "filas": construir_filas(
            [
                ["04:25","04:37","04:54","05:40","06:17","06:29","06:46","06:58","07:10"],
                ["05:00","05:12","05:29","06:25","07:02","07:14","07:31","07:43","07:55"],
                ["05:45","05:57","06:14","07:10","07:47","07:59","08:16","08:28","08:40"],
                ["06:30","06:42","06:59","07:55","08:32","08:44","09:01","09:13","09:25"]
            ],
            ["07:22","08:07","08:52","09:37","10:10","10:55","11:40","12:25","12:58","13:43","14:28","15:13","15:46","16:31","17:16","18:01","18:34","19:19","20:04","20:49","21:22","22:07","22:52"],
            [0, 12, 17, 37, 37, 12, 17, 12, 12],
            ["23:37","23:49","00:06","00:43","-","-","-","-","-"]
        )
    },
    "50A_DOM": {
        "nombre": "50A Domingo",
        "columnas": ["Loteo Social", "San Martín y Trabajo", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "Ruta 22 y Riavitz", "Amancay y Muticias", "Casa Cultura", "Loteo Social"],
        "filas": construir_filas(
            [
                ["05:30","05:42","05:59","07:00","07:30","07:45","08:00","08:15","08:27"],
                ["06:10","06:22","06:39","07:34","08:04","08:19","08:34","08:49","09:01"],
                ["06:50","07:02","07:19","08:14","08:44","08:59","09:14","09:29","09:41"]
            ],
            ["08:40","09:30","10:20","11:19","12:09","12:59","13:58","14:48","15:38","16:37","17:27","18:17","19:16","20:06","20:56","21:55","22:45"],
            [0, 12, 17, 30, 30, 15, 15, 15, 12],
            ["23:35","23:47","00:04","00:34","-","-","-","-","-"]
        )
    },
    "50B_HABIL": {
        "nombre": "50B Hábil",
        "columnas": ["Loteo Social", "Casa Cultura", "Amancay y Muticias", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "San Martín y Trabajo", "Loteo Social"],
        "filas": construir_filas(
            [
                ["04:30","04:45","05:00","05:20","05:55","06:32","06:52","07:04"],
                ["05:03","05:18","05:33","05:53","06:28","07:05","07:25","07:37"],
                ["05:36","05:51","06:06","06:26","07:01","07:38","07:58","08:10"],
                ["06:09","06:24","06:39","06:59","07:34","08:11","08:31","08:43"],
                ["06:42","06:57","07:12","07:32","08:07","08:44","09:04","09:16"]
            ],
            ["07:14","07:47","08:20","08:53","09:26","10:00","10:33","11:06","11:39","12:12","12:46","13:19","13:52","14:25","14:58","15:32","16:05","16:38","17:11","17:44","18:18","18:51","19:24","19:57","20:30","21:04","21:37","22:10","22:43"],
            [0, 15, 15, 20, 37, 37, 20, 12],
            ["23:16","23:31","23:46","00:06","00:43","-","-","-"]
        )
    },
    "50B_SAB": {
        "nombre": "50B Sábado",
        "columnas": ["Loteo Social", "Casa Cultura", "Amancay y Muticias", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "San Martín y Trabajo", "Loteo Social"],
        "filas": construir_filas(
            [
                ["04:30","04:45","05:00","05:20","05:55","06:32","06:52","07:04"],
                ["05:15","05:30","05:45","06:05","06:40","07:17","07:37","07:49"],
                ["06:00","06:15","06:30","06:50","07:25","08:02","08:22","08:34"]
            ],
            ["06:44","07:29","08:14","08:59","09:32","10:17","11:02","11:47","12:20","13:05","13:50","14:35","15:08","15:53","16:38","17:23","17:56","18:41","19:26","20:11","20:44","21:29","22:14"],
            [0, 15, 15, 20, 37, 37, 20, 12],
            ["22:59","23:14","23:29","23:49","00:26","-","-","-"]
        )
    },
    "50B_DOM": {
        "nombre": "50B Domingo",
        "columnas": ["Loteo Social", "Casa Cultura", "Amancay y Muticias", "Río Colorado (Ida)", "San Juan y Bs As", "Río Colorado (Vta)", "San Martín y Trabajo", "Loteo Social"],
        "filas": construir_filas(
            [
                ["05:40","05:53","06:06","06:26","06:34","07:09","07:29","07:39"],
                ["06:20","06:33","06:46","07:06","07:14","07:49","08:09","08:19"],
                ["07:00","07:13","07:26","07:46","07:54","08:29","08:49","08:59"]
            ],
            ["07:52","08:46","09:36","10:31","11:25","12:15","13:10","14:04","14:54","15:49","16:43","17:33","18:28","19:22","20:12","21:07","22:01"],
            [0, 13, 13, 20, 35, 35, 20, 10],
            ["22:51","23:04","23:17","23:37","00:12","-","-","-"]
        )
    },
    "50R_HABIL": {
        "nombre": "50R Hábil y Sábado",
        "columnas": ["El Mangrullo", "Ruta 22 ETOP (Ida)", "Altura Aeropuerto (Ida)", "Altura ETON (Ida)", "Parque Central Nqn", "Altura ETON (Vta)", "Altura Aeropuerto (Vta)", "Ruta 22 ETOP (Vta)", "El Mangrullo"],
        "filas": construir_filas(
            [],
            ["05:15","06:10","07:05","08:15","09:10","10:05","11:15","12:10","13:05","14:15","15:10","16:05","17:15","18:10","19:05","20:15","21:10","22:05"],
            [0, 48, 12, 7, 18, 18, 7, 13, 47],
            ["-","-","-","-","00:30","00:48","00:55","01:08","01:55"]
        ) + [
            ["23:15","00:03","00:15","00:22","00:40","00:58","01:05","01:18","02:05"]
        ]
    },
    "TREN_HABIL": {
        "nombre": "Tren del Valle (Lunes a Viernes)",
        "columnas": [
            "Plottier (Sal.)", "Constituyentes (Ida)", "B° Unión (Ida)", "Aeropuerto (Ida)",
            "El Cholar (Ida)", "ETON (Ida)", "Ignacio Rivas (Ida)", "Neuquén (Ida)",
            "Cipolletti",
            "Neuquén (Vta)", "Ignacio Rivas (Vta)", "ETON (Vta)", "El Cholar (Vta)",
            "Aeropuerto (Vta)", "B° Unión (Vta)", "Constituyentes (Vta)", "Plottier (Lleg.)"
        ],
        "filas": construir_filas(
            [
                # Primer servicio corto matutino Plottier <-> Barrio Unión
                ["05:55","06:02","06:07","-","-","-","-","-","-","-","-","-","-","-","06:15","06:20","06:27"]
            ],
            ["06:35","07:50","09:25","11:10","12:55","14:40","16:25","18:10","19:55"],
            [0, 7, 5, 6, 5, 4, 15, 10, 20, 22, 10, 15, 4, 5, 6, 5, 7],
            ["21:20","21:27","21:32","21:38","21:43","21:47","22:02","22:12","22:32","-","-","-","-","-","-","-","-"]
        )
    }
}

def obtener_horarios_oficiales():
    return {
        "puntos_control": PUNTOS_CONTROL_OFICIALES,
        "orden_paradas": ORDEN_PARADAS,
        "planillas": PLANILLAS_OFICIALES,
        "traza_tren": TRAZA_TREN_GEO
    }

HTML_COMPLETO = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Transporte Plottier - Colectivos y Tren del Valle en Vivo</title>

  <link rel="icon" type="image/png" sizes="512x512" href="/logo.png">
  <link rel="icon" type="image/png" sizes="192x192" href="/logo.png">
  <link rel="shortcut icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/logo.png">

  <meta name="description" content="Ubicación GPS en vivo y horarios oficiales de las líneas 50A, 50B, 50R, 51 Urbano, 52 y Tren del Valle en Plottier, Neuquén y Cipolletti.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Transporte Plottier">
  <meta property="og:title" content="Transporte Plottier - Colectivos y Tren en Vivo">
  <meta property="og:description" content="Seguimiento en tiempo real y planillas oficiales (50A, 50B, 50R, 51 Urbano, 52 y Tren del Valle).">
  <meta property="og:url" content="{{ base_url }}/">
  <meta property="og:image" content="{{ base_url }}/logo.png">
  <meta property="og:image:width" content="512">
  <meta property="og:image:height" content="512">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="Transporte Plottier - Colectivos y Tren en Vivo">
  <meta name="twitter:description" content="GPS en vivo y planillas oficiales de colectivos y Tren del Valle en Plottier y Neuquén.">
  <meta name="twitter:image" content="{{ base_url }}/logo.png">

  <!-- Google tag (gtag.js) - Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-CE85R9NET5"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-CE85R9NET5');
  </script>

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #181825; color: #CDD6F4; padding: 16px 14px 98px; max-width: 980px; margin: 0 auto; }
    header { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
    .brand-wrap { display: flex; align-items: center; gap: 10px; }
    .brand-logo { width: 38px; height: 38px; border-radius: 9px; object-fit: cover; border: 1px solid #313244; flex-shrink: 0; }
    h1 { font-size: 22px; color: #89B4FA; font-weight: 800; }
    .sub { font-size: 13px; color: #A6ADC8; margin-top: 2px; }
    .badge-beta { background: rgba(249, 226, 175, 0.12); color: #F9E2AF; border: 1px solid rgba(249, 226, 175, 0.4); font-size: 10px; font-weight: 800; padding: 4px 8px; border-radius: 6px; letter-spacing: 0.4px; text-transform: uppercase; }

    #map-container { position: relative; margin-bottom: 16px; border-radius: 14px; overflow: hidden; border: 1px solid #313244; box-shadow: 0 4px 20px rgba(0,0,0,0.35); }
    #map { height: 460px; width: 100%; background: #11111B; }
    .map-badge { position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(24, 24, 37, 0.92); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 8px; font-size: 12px; color: #CDD6F4; border: 1px solid #313244; font-weight: 700; }
    .map-controls { position: absolute; bottom: 10px; right: 10px; z-index: 1000; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .btn-map-control { background: rgba(24, 24, 37, 0.92); border: 1px solid #45475A; color: #CDD6F4; font-size: 11px; font-weight: 700; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    
    .bar-fixed { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(24, 24, 37, 0.96); backdrop-filter: blur(10px); padding: 12px 16px; border-top: 1px solid #313244; display: flex; justify-content: space-between; align-items: center; z-index: 2000; }
    .btn-refresh { background: #89B4FA; color: #11111B; border: none; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 10px; cursor: pointer; }
    .status-text { font-size: 12px; color: #A6ADC8; }

    .bus-marker { display: flex; align-items: center; justify-content: center; gap: 4px; padding: 3px 7px; border-radius: 8px; font-size: 11px; font-weight: 800; white-space: nowrap; box-shadow: 0 2px 6px rgba(0,0,0,0.65); position: relative; }
    .bus-marker-50a { background: #1E3A24; border: 2px solid #A6E3A1; color: #A6E3A1; }
    .bus-marker-50b { background: #1E2D42; border: 2px solid #89B4FA; color: #89B4FA; }
    .bus-marker-50r { background: #38243E; border: 2px solid #CBA6F7; color: #CBA6F7; }
    .bus-marker-urbano { background: #3E3724; border: 2px solid #F9E2AF; color: #F9E2AF; }
    .bus-marker-52 { background: #3E2824; border: 2px solid #FAB387; color: #FAB387; }
    .bus-marker-tren { background: #112A38; border: 2px solid #89DCEB; color: #89DCEB; box-shadow: 0 2px 10px rgba(137, 220, 235, 0.4); }

    .bus-weak { border-style: dashed !important; border-color: #F9E2AF !important; animation: pulseWeak 1.6s infinite; }
    .bus-stalled { background: #3B1D26 !important; border-color: #F38BA8 !important; color: #F38BA8 !important; opacity: 0.88; }
    .bus-cabecera { opacity: 0.78; border-style: dotted !important; }

    @keyframes pulseWeak {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }

    .stop-featured-pin {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #1E3A24;
      border: 2px solid #A6E3A1;
      color: #A6E3A1;
      font-size: 12px;
      font-weight: 900;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 6px rgba(0,0,0,0.75);
      cursor: pointer;
    }

    .stop-train-pin {
      width: 24px;
      height: 24px;
      border-radius: 7px;
      background: #112A38;
      border: 2px solid #89DCEB;
      color: #89DCEB;
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 7px rgba(0,0,0,0.8);
      cursor: pointer;
    }

    .stop-popup-title { font-size: 13px; font-weight: 800; color: #111; }
    .stop-popup-badge { display: inline-block; background: #e8f8f5; color: #117a65; border: 1px solid #a3e4d7; font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 4px; margin-bottom: 4px; }
    .stop-popup-badge-train { display: inline-block; background: #e8f4f8; color: #0e6287; border: 1px solid #94d2bd; font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 4px; margin-bottom: 4px; }
    .stop-popup-desc { font-size: 11px; color: #555; margin-bottom: 6px; }
    .btn-query-stop { background: #1E1E2E; color: #CDD6F4; border: 1px solid #45475A; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; margin: 2px; }
    .btn-jump-sched { display: inline-block; margin-top: 5px; background: #25335A; color: #89B4FA; border: 1px solid #89B4FA; padding: 3px 8px; border-radius: 5px; font-size: 10.5px; font-weight: 800; cursor: pointer; width: 100%; text-align: center; }
    .result-box { margin-top: 6px; padding-top: 4px; border-top: 1px solid #ccc; font-size: 11px; color: #111; }

    /* Sección de Planillas y Horarios Oficiales */
    .sched-card {
      background: #1E1E2E;
      border: 1px solid #313244;
      border-radius: 14px;
      padding: 14px 16px;
      margin-bottom: 14px;
      scroll-margin-top: 16px;
    }
    .sched-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      user-select: none;
    }
    .sched-header-title {
      font-size: 13.5px;
      font-weight: 800;
      color: #89B4FA;
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .sched-header-btn {
      background: #313244;
      color: #CDD6F4;
      border: 1px solid #45475A;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 9px;
      border-radius: 7px;
    }
    .sched-content {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #313244;
      display: none;
    }
    .sched-tabs {
      display: flex;
      gap: 6px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .sched-tab {
      background: #252739;
      color: #A6ADC8;
      border: 1px solid #45475A;
      padding: 5px 11px;
      border-radius: 8px;
      font-size: 11.5px;
      font-weight: 700;
      cursor: pointer;
    }
    .sched-tab.active {
      background: #89B4FA;
      color: #11111B;
      border-color: #89B4FA;
    }
    .sched-legend {
      display: none;
      background: #181825;
      border: 1px solid #313244;
      border-radius: 8px;
      padding: 8px 10px;
      margin-bottom: 10px;
      font-size: 11px;
      color: #CDD6F4;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px;
    }
    .legend-items {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .legend-tag {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 10.5px;
      font-weight: 700;
    }
    .dot-zone { width: 11px; height: 11px; border-radius: 3px; background: rgba(137, 180, 250, 0.35); border: 2px solid #89B4FA; display: inline-block; }
    .dot-next { width: 11px; height: 11px; border-radius: 3px; background: #1E3A24; border: 2px solid #A6E3A1; display: inline-block; }
    .btn-clear-sched {
      background: #313244;
      color: #F38BA8;
      border: 1px solid #45475A;
      font-size: 10.5px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      cursor: pointer;
    }

    .table-responsive {
      max-height: 400px;
      overflow-y: auto;
      overflow-x: auto;
      border-radius: 8px;
      border: 1px solid #313244;
      position: relative;
    }
    table.sched-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 11px;
      text-align: center;
      background: #181825;
      color: #CDD6F4;
    }
    table.sched-table th {
      background: #1E1E2E;
      color: #89B4FA;
      padding: 8px 5px;
      font-weight: 800;
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid #313244;
      font-size: 10.5px;
      white-space: nowrap;
    }
    table.sched-table td {
      padding: 6px 5px;
      border-bottom: 1px solid #262738;
      white-space: nowrap;
    }

    table.sched-table th.col-zone-active {
      background: #22325A !important;
      color: #FFFFFF !important;
      border-top: 2px solid #89B4FA !important;
      border-left: 2px solid #89B4FA !important;
      border-right: 2px solid #89B4FA !important;
      box-shadow: 0 2px 8px rgba(137, 180, 250, 0.35);
    }
    table.sched-table td.col-zone-active {
      background: rgba(137, 180, 250, 0.16) !important;
      color: #FFFFFF !important;
      font-weight: 700;
      border-left: 2px solid #89B4FA !important;
      border-right: 2px solid #89B4FA !important;
    }
    table.sched-table tr:last-child td.col-zone-active {
      border-bottom: 2px solid #89B4FA !important;
    }

    table.sched-table td.cell-next-arrival {
      background: #1E3A24 !important;
      color: #A6E3A1 !important;
      font-weight: 900 !important;
      box-shadow: inset 0 0 0 2px #A6E3A1 !important;
    }

    table.sched-table td.cell-next-stops {
      background: rgba(249, 226, 175, 0.20) !important;
      color: #F9E2AF !important;
      font-weight: 800 !important;
      border-top: 1px dashed rgba(249, 226, 175, 0.75) !important;
      border-bottom: 1px dashed rgba(249, 226, 175, 0.75) !important;
    }

    /* Sección Posdata / Acerca de la app */
    .about-card {
      background: #1E1E2E;
      border: 1px solid #313244;
      border-radius: 14px;
      padding: 16px;
      color: #BAC2DE;
      font-size: 12.5px;
      line-height: 1.55;
    }
    .about-title {
      font-size: 13px;
      font-weight: 800;
      color: #89B4FA;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .about-text {
      color: #A6ADC8;
      margin-bottom: 10px;
    }
    .beta-notice {
      background: rgba(249, 226, 175, 0.07);
      border-left: 3px solid #F9E2AF;
      padding: 8px 10px;
      border-radius: 4px 8px 8px 4px;
      font-size: 11.5px;
      color: #CBD2EB;
      margin-bottom: 14px;
    }
    .author-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      padding-top: 12px;
      border-top: 1px solid #313244;
    }
    .author-info {
      display: flex;
      align-items: center;
      gap: 11px;
    }
    .author-avatar-wrap {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      overflow: hidden;
      border: 2px solid #89B4FA;
      background: #313244;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .author-avatar {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .author-initials {
      font-size: 14px;
      font-weight: 800;
      color: #89B4FA;
      display: none;
    }
    .author-name {
      font-size: 13.5px;
      font-weight: 800;
      color: #CDD6F4;
    }
    .author-role {
      font-size: 11.5px;
      color: #9399B2;
    }
    .contact-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #313244;
      color: #A6E3A1;
      border: 1px solid #45475A;
      padding: 7px 12px;
      border-radius: 9px;
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
      transition: background 0.15s ease;
    }
    .contact-btn:hover {
      background: #45475A;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand-wrap">
      <img src="/logo.png" alt="Logo" class="brand-logo" onerror="this.style.display='none';">
      <div>
        <h1>Transporte Plottier</h1>
        <p class="sub">GPS en vivo y planillas oficiales (50A, 50B, 50R, 51 Urbano, 52 y Tren del Valle)</p>
      </div>
    </div>
    <span class="badge-beta">Versión Beta</span>
  </header>

  <div id="map-container">
    <div class="map-badge" id="bus-count">Sincronizando radar...</div>
    <div class="map-controls">
      <button class="btn-map-control" onclick="mostrarRuta('TREN', 'HACIA_NEUQUEN')">🚆 Ver Vía del Tren</button>
      <button class="btn-map-control" id="btn-toggle-stops" onclick="toggleParadas()">📍 Ocultar Paradas</button>
      <button class="btn-map-control" id="btn-clear" onclick="limpiarRutas()" style="display:none;">✕ Quitar Recorrido</button>
    </div>
    <div id="map"></div>
  </div>

  <!-- Desplegable de Planillas de Horarios Oficiales -->
  <section class="sched-card" id="sched-section">
    <div class="sched-header" onclick="togglePlanillas()">
      <div class="sched-header-title" id="sched-title-text">📅 Horarios Oficiales Indalo y Tren del Valle</div>
      <button class="sched-header-btn" id="btn-sched-toggle">Ver Planilla ▾</button>
    </div>
    <div class="sched-content" id="sched-panel">
      <div class="sched-tabs">
        <button class="sched-tab active" data-clave="50A_HABIL" onclick="mostrarPlanilla('50A_HABIL')">50A Hábil</button>
        <button class="sched-tab" data-clave="50A_SAB" onclick="mostrarPlanilla('50A_SAB')">50A Sábado</button>
        <button class="sched-tab" data-clave="50A_DOM" onclick="mostrarPlanilla('50A_DOM')">50A Domingo</button>
        <button class="sched-tab" data-clave="50B_HABIL" onclick="mostrarPlanilla('50B_HABIL')">50B Hábil</button>
        <button class="sched-tab" data-clave="50B_SAB" onclick="mostrarPlanilla('50B_SAB')">50B Sábado</button>
        <button class="sched-tab" data-clave="50B_DOM" onclick="mostrarPlanilla('50B_DOM')">50B Domingo</button>
        <button class="sched-tab" data-clave="50R_HABIL" onclick="mostrarPlanilla('50R_HABIL')">50R Hábil y Sáb</button>
        <button class="sched-tab" data-clave="TREN_HABIL" onclick="mostrarPlanilla('TREN_HABIL')">🚆 Tren del Valle</button>
      </div>
      <div class="sched-legend" id="sched-legend-box">
        <div class="legend-items">
          <span class="legend-tag"><span class="dot-zone"></span> <span id="legend-zone-name">Zona seleccionada</span></span>
          <span class="legend-tag"><span class="dot-next"></span> Próximos arribos aquí</span>
          <span class="legend-tag"><span style="width:11px;height:11px;border-radius:3px;background:rgba(249,226,175,0.28);border:2px solid #F9E2AF;display:inline-block;"></span> Horarios en próximas paradas</span>
        </div>
        <button class="btn-clear-sched" onclick="limpiarResaltadoPlanilla()">✕ Quitar filtro</button>
      </div>
      <div class="table-responsive" id="sched-table-box"></div>
    </div>
  </section>

  <!-- Posdata / Nota del desarrollador -->
  <section class="about-card">
    <div class="about-title">💡 P.D. · Proyecto libre y comunitario</div>
    <p class="about-text">
      Esta es una aplicación libre y gratuita pensada para los vecinos de <strong>Plottier</strong> y el público en general.
      Surgió originalmente como una herramienta para mi familia ante la falta de una forma práctica de ver los colectivos y sus recorridos en tiempo real, y decidí abrirla a la comunidad. Cada quien es totalmente libre de usarla y compartirla con quien guste.
    </p>
    <div class="beta-notice">
      ⚠ <strong>Aviso importante:</strong> La aplicación se encuentra en fase <strong>Beta y en constante desarrollo</strong>. Las ubicaciones en movimiento y los tiempos son estimaciones basadas en los reportes del sistema y cronogramas oficiales, por lo que pueden existir demoras o variaciones operativas.
    </div>
    <div class="author-row">
      <div class="author-info">
        <div class="author-avatar-wrap">
          <img src="/foto_perfil" alt="Ramiro Alzogaray" class="author-avatar"
               onerror="this.style.display='none'; document.getElementById('avatar-fallback').style.display='block';">
          <span id="avatar-fallback" class="author-initials">RA</span>
        </div>
        <div>
          <div class="author-name">Ramiro Alzogaray</div>
          <div class="author-role">Desarrollador · Plottier, Neuquén</div>
        </div>
      </div>
      <a class="contact-btn" href="https://wa.me/5492994601098" target="_blank" rel="noopener noreferrer" title="Enviar sugerencia o reportar un error">
        💬 Sugerencias / Errores: 299 460-1098
      </a>
    </div>
  </section>

  <div class="bar-fixed">
    <button id="btn" class="btn-refresh" onclick="pedirDatos()">Actualizar</button>
    <div class="status-text" id="status">Sincronizando...</div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    let map, capaRuta, capaParadas;
    let busesSim = {};
    let trenesSim = {};
    let totalBusesRadar = 0;
    let totalBusesEnVivo = 0;
    let RUTAS_GEO = {};
    let RUTAS_DENSAS = {};
    let PUNTOS_CONTROL_OFICIALES = [];
    let ORDEN_PARADAS_OFICIALES = {};
    let PLANILLAS_INDALO = {};
    let mostrandoParadas = true;
    let planillasAbiertas = false;
    let clavePlanillaActual = "50A_HABIL";
    let puntoKeyResaltado = null;

    const LIMITE_DEBIL_SEG = 180;
    const LIMITE_AVERIA_SEG = 240;
    const DIST_MAX_EN_RUTA_MTS = 35;

    // Correspondencia exacta entre las 17 columnas de TREN_HABIL y las claves de estaciones
    const MAPA_COL_ESTACION_TREN = [
      "TREN_PLOTTIER", "TREN_CONSTITUYENTES", "TREN_UNION", "TREN_AEROPUERTO",
      "TREN_CHOLAR", "TREN_ETON", "TREN_RIVAS", "TREN_NEUQUEN",
      "TREN_CIPOLLETTI",
      "TREN_NEUQUEN", "TREN_RIVAS", "TREN_ETON", "TREN_CHOLAR",
      "TREN_AEROPUERTO", "TREN_UNION", "TREN_CONSTITUYENTES", "TREN_PLOTTIER"
    ];

    function sumarMinutos(hhmm, mins) {
      const partes = String(hhmm).split(':');
      let mTotal = parseInt(partes[0], 10) * 60 + parseInt(partes[1], 10) + (mins || 0);
      mTotal = (mTotal % 1440 + 1440) % 1440;
      const h = String(Math.floor(mTotal / 60)).padStart(2, '0');
      const m = String(mTotal % 60).padStart(2, '0');
      return `${h}:${m}`;
    }

    function hhmmAMinutos(hhmm) {
      const partes = String(hhmm).split(':');
      return parseInt(partes[0], 10) * 60 + parseInt(partes[1], 10);
    }

    function obtenerMinutoInicioFila(fila) {
      for (const c of fila) {
        if (c && c !== "-") return hhmmAMinutos(c);
      }
      return 0;
    }

    function calcularDiferenciaHorario(minPasoBase, minInicioFila, minActual) {
      const minPasoMonotono = (minPasoBase < minInicioFila && minInicioFila >= 1080)
        ? minPasoBase + 1440
        : minPasoBase;

      if (minActual < 135 && minPasoMonotono >= 1440) {
        return minPasoMonotono - (minActual + 1440);
      }
      return minPasoMonotono - minActual;
    }

    function obtenerMinutosActualesArgentina() {
      const ahora = new Date();
      const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Argentina/Buenos_Aires',
        hour: '2-digit', minute: '2-digit', second: '2-digit', weekday: 'short', hour12: false
      }).formatToParts(ahora);
      let h = 0, m = 0, s = 0, wd = 'Mon';
      for (const p of fmt) {
        if (p.type === 'hour') h = parseInt(p.value, 10) % 24;
        if (p.type === 'minute') m = parseInt(p.value, 10);
        if (p.type === 'second') s = parseInt(p.value, 10);
        if (p.type === 'weekday') wd = p.value;
      }
      const minActual = h * 60 + m;
      const minExacto = minActual + (s / 60.0);

      let wdOperativo = wd;
      if (minActual < 130) {
        const mapaPrevio = { Mon: 'Sun', Tue: 'Mon', Wed: 'Tue', Thu: 'Wed', Fri: 'Thu', Sat: 'Fri', Sun: 'Sat' };
        wdOperativo = mapaPrevio[wd] || wd;
      }

      let sufijoDia = 'HABIL';
      let etiquetaDia = 'Día Hábil';
      if (wdOperativo === 'Sat') {
        sufijoDia = 'SAB';
        etiquetaDia = 'Sábado';
      } else if (wdOperativo === 'Sun') {
        sufijoDia = 'DOM';
        etiquetaDia = 'Domingo';
      }

      const sufijoCalendario = (wd === 'Sat') ? 'SAB' : ((wd === 'Sun') ? 'DOM' : 'HABIL');
      return {
        minActual: minActual,
        minExacto: minExacto,
        sufijoDia: sufijoDia,
        sufijoCalendario: sufijoCalendario,
        etiquetaDia: etiquetaDia
      };
    }

    function resolverClavePlanilla(linNom, sufijoDia) {
      if (linNom === "TREN") return "TREN_HABIL";
      if (linNom === "50R") return "50R_HABIL";
      const candidata = `${linNom}_${sufijoDia}`;
      return PLANILLAS_INDALO[candidata] ? candidata : `${linNom}_HABIL`;
    }

    function togglePlanillas() {
      const p = document.getElementById('sched-panel');
      const b = document.getElementById('btn-sched-toggle');
      planillasAbiertas = !planillasAbiertas;
      if (planillasAbiertas) {
        p.style.display = 'block';
        b.innerText = 'Ocultar Planilla ▴';
        mostrarPlanilla(clavePlanillaActual);
      } else {
        p.style.display = 'none';
        b.innerText = 'Ver Planilla ▾';
      }
    }

    function limpiarResaltadoPlanilla() {
      puntoKeyResaltado = null;
      document.getElementById('sched-legend-box').style.display = 'none';
      document.getElementById('sched-title-text').innerText = '📅 Horarios Oficiales Indalo y Tren del Valle';
      mostrarPlanilla(clavePlanillaActual);
    }

    function obtenerColsPuntoSegunLinea(punto, linNom) {
      if (!punto) return [];
      if (linNom === "50A") return punto.cols50A || [];
      if (linNom === "50B") return punto.cols50B || [];
      if (linNom === "50R") return punto.cols50R || [];
      if (linNom === "TREN") return punto.colsTREN || [];
      return [];
    }

    function desplegarPlanillaConZona(puntoKey, lineaPreferida = null) {
      const punto = PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKey);
      if (!punto) return;

      puntoKeyResaltado = puntoKey;
      const infoTiempo = obtenerMinutosActualesArgentina();

      let lin = lineaPreferida;
      if (!lin || obtenerColsPuntoSegunLinea(punto, lin).length === 0) {
        if ((punto.colsTREN || []).length > 0) lin = "TREN";
        else if ((punto.cols50A || []).length > 0) lin = "50A";
        else if ((punto.cols50B || []).length > 0) lin = "50B";
        else if ((punto.cols50R || []).length > 0) lin = "50R";
        else lin = "50A";
      }

      const clave = resolverClavePlanilla(lin, infoTiempo.sufijoDia);
      clavePlanillaActual = clave;

      const p = document.getElementById('sched-panel');
      const b = document.getElementById('btn-sched-toggle');
      planillasAbiertas = true;
      p.style.display = 'block';
      b.innerText = 'Ocultar Planilla ▴';

      mostrarPlanilla(clave);
    }

    function irALaPlanillaAbajo() {
      const sec = document.getElementById('sched-section');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function mostrarPlanilla(clave) {
      if (!PLANILLAS_INDALO[clave]) return;
      clavePlanillaActual = clave;

      document.querySelectorAll('.sched-tab').forEach(t => {
        if (t.getAttribute('data-clave') === clave) t.classList.add('active');
        else t.classList.remove('active');
      });

      const data = PLANILLAS_INDALO[clave];
      const linActual = clave.split('_')[0];
      const infoTiempo = obtenerMinutosActualesArgentina();

      const colsSeleccionadas = new Set();
      const celdasProximoArribo = new Map();
      const celdasProximasParadas = new Set();
      let primeraFilaResaltada = -1;
      let primeraColResaltada = -1;

      const punto = puntoKeyResaltado ? PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKeyResaltado) : null;
      const legendBox = document.getElementById('sched-legend-box');
      const titleText = document.getElementById('sched-title-text');

      if (punto) {
        const listaCols = obtenerColsPuntoSegunLinea(punto, linActual);
        if (listaCols.length > 0) {
          legendBox.style.display = 'flex';
          document.getElementById('legend-zone-name').innerText = `Zona: ${punto.nombreOficial}`;
          titleText.innerText = `📅 Planilla Oficial · Zona resaltada: ${punto.nombreOficial}`;

          listaCols.forEach(cObj => {
            const cIdx = cObj.idx;
            const offsetMin = cObj.offset || 0;
            colsSeleccionadas.add(cIdx);
            if (primeraColResaltada === -1) primeraColResaltada = cIdx;

            const candidatos = [];
            data.filas.forEach((fila, rIdx) => {
              const hhmmBase = fila[cIdx];
              if (!hhmmBase || hhmmBase === "-") return;
              const minInicioFila = obtenerMinutoInicioFila(fila);
              const hhmm = offsetMin !== 0 ? sumarMinutos(hhmmBase, offsetMin) : hhmmBase;
              const minPaso = hhmmAMinutos(hhmm);
              const dif = calcularDiferenciaHorario(minPaso, minInicioFila, infoTiempo.minActual);

              const maxVentana = linActual === "TREN" ? 720 : 240;
              if (dif >= 0 && dif <= maxVentana) {
                candidatos.push({ rIdx, dif, hhmm });
              }
            });

            candidatos.sort((a, b) => a.dif - b.dif);
            const topFilas = candidatos.slice(0, 3);

            topFilas.forEach((item, orden) => {
              celdasProximoArribo.set(`${item.rIdx}_${cIdx}`, item.hhmm);
              if (primeraFilaResaltada === -1) primeraFilaResaltada = item.rIdx;

              if (orden < 2) {
                const limiteCol = (linActual === "TREN" && cIdx <= 8) ? 9 : data.columnas.length;
                for (let nextCol = cIdx + 1; nextCol < limiteCol; nextCol++) {
                  const valSig = data.filas[item.rIdx][nextCol];
                  if (valSig && valSig !== "-") {
                    celdasProximasParadas.add(`${item.rIdx}_${nextCol}`);
                  }
                }
              }
            });
          });
        } else {
          legendBox.style.display = 'none';
          titleText.innerText = '📅 Horarios Oficiales Indalo y Tren del Valle';
        }
      } else {
        legendBox.style.display = 'none';
        titleText.innerText = '📅 Horarios Oficiales Indalo y Tren del Valle';
      }

      let h = `<table class="sched-table"><thead><tr>`;
      data.columnas.forEach((col, cIdx) => {
        const claseCol = colsSeleccionadas.has(cIdx) ? 'col-zone-active' : '';
        const icono = colsSeleccionadas.has(cIdx) ? '📍 ' : '';
        h += `<th class="${claseCol}" id="sched-th-${cIdx}">${icono}${col}</th>`;
      });
      h += `</tr></thead><tbody>`;

      data.filas.forEach((fila, rIdx) => {
        h += `<tr id="sched-tr-${rIdx}">`;
        fila.forEach((celda, cIdx) => {
          const keyCelda = `${rIdx}_${cIdx}`;
          const clases = [];
          if (colsSeleccionadas.has(cIdx)) clases.push('col-zone-active');
          if (celdasProximoArribo.has(keyCelda)) {
            clases.push('cell-next-arrival');
          } else if (celdasProximasParadas.has(keyCelda)) {
            clases.push('cell-next-stops');
          }

          const prefijo = celdasProximoArribo.has(keyCelda)
            ? '⏱ '
            : (celdasProximasParadas.has(keyCelda) ? '➔ ' : '');

          const textoCelda = celdasProximoArribo.has(keyCelda)
            ? celdasProximoArribo.get(keyCelda)
            : celda;

          h += `<td class="${clases.join(' ')}">${prefijo}${textoCelda}</td>`;
        });
        h += `</tr>`;
      });
      h += `</tbody></table>`;

      const tableBox = document.getElementById('sched-table-box');
      tableBox.innerHTML = h;

      setTimeout(() => {
        if (primeraFilaResaltada !== -1) {
          const trEl = document.getElementById(`sched-tr-${Math.max(0, primeraFilaResaltada - 1)}`);
          if (trEl) tableBox.scrollTop = Math.max(0, trEl.offsetTop - 42);
        }
        if (primeraColResaltada !== -1 && tableBox.scrollWidth > tableBox.clientWidth + 40) {
          const thEl = document.getElementById(`sched-th-${Math.max(0, primeraColResaltada)}`);
          if (thEl) tableBox.scrollLeft = Math.max(0, thEl.offsetLeft - 80);
        } else {
          tableBox.scrollLeft = 0;
        }
      }, 60);
    }

    function calcularHorariosPuntoOficial(puntoKey, linNom) {
      if (linNom !== "50A" && linNom !== "50B" && linNom !== "50R" && linNom !== "TREN") return null;
      const punto = PUNTOS_CONTROL_OFICIALES.find(p => p.key === puntoKey);
      if (!punto) return null;

      const cols = obtenerColsPuntoSegunLinea(punto, linNom);
      if (cols.length === 0) return null;

      const infoTiempo = obtenerMinutosActualesArgentina();
      const clavePlan = resolverClavePlanilla(linNom, infoTiempo.sufijoDia);
      const planilla = PLANILLAS_INDALO[clavePlan];
      if (!planilla) return null;

      const sinServicioHoy = (linNom === "TREN" && infoTiempo.sufijoCalendario !== "HABIL");
      const etiquetaPlan = (linNom === "TREN")
        ? "Lunes a Viernes"
        : ((linNom === "50R")
          ? (infoTiempo.sufijoDia === "DOM" ? "Ref. Hábil/Sáb" : "Hábil / Sáb")
          : infoTiempo.etiquetaDia);

      const resultados = [];
      const maxVentana = linNom === "TREN" ? 720 : 240;

      for (const cInfo of cols) {
        const offsetMin = cInfo.offset || 0;
        const proximos = [];
        for (const fila of planilla.filas) {
          const hhmmBase = fila[cInfo.idx];
          if (!hhmmBase || hhmmBase === "-") continue;
          const minInicioFila = obtenerMinutoInicioFila(fila);
          const hhmm = offsetMin !== 0 ? sumarMinutos(hhmmBase, offsetMin) : hhmmBase;
          const minPaso = hhmmAMinutos(hhmm);
          let dif = calcularDiferenciaHorario(minPaso, minInicioFila, infoTiempo.minActual);
          if (linNom === "TREN" && dif < 0) dif += 1440;

          if (dif >= 0 && dif <= maxVentana) {
            proximos.push({ hora: hhmm, enMin: dif });
          }
        }
        proximos.sort((a, b) => a.enMin - b.enMin);
        if (proximos.length > 0) {
          resultados.push({
            sentidoLabel: cInfo.label,
            proximo: proximos[0],
            siguientes: proximos.slice(0, 3)
          });
        }
      }
      return { etiquetaDia: etiquetaPlan, sinServicioHoy: sinServicioHoy, bloques: resultados };
    }

    function armarHTMLHorarioProgramado(puntoKey, linNom, incluirBoton = false) {
      const info = calcularHorariosPuntoOficial(puntoKey, linNom);
      if (!info || !info.bloques || info.bloques.length === 0) return '';

      let html = `<div style="margin-top:5px; padding-top:4px; border-top:1px dashed #bbb; font-size:11px; color:#222;">`;
      if (info.sinServicioHoy) {
        html += `<div style="color:#b7950b; font-weight:800; margin-bottom:4px;">⏸ Sin servicio hoy (opera lunes a viernes hábiles)</div>`;
      }
      info.bloques.forEach(b => {
        let textoEnCuanto = "";
        if (info.sinServicioHoy) {
          textoEnCuanto = `Próximo hábil: <strong>${b.proximo.hora}</strong>`;
        } else if (b.proximo.enMin === 0) {
          textoEnCuanto = "¡En estación ahora!";
        } else if (b.proximo.enMin > 90) {
          const hs = Math.floor(b.proximo.enMin / 60);
          const ms = b.proximo.enMin % 60;
          textoEnCuanto = `Sale en <strong>${hs}h ${ms}m</strong> (${b.proximo.hora})`;
        } else {
          textoEnCuanto = `Pasa en <strong>${b.proximo.enMin} min</strong>`;
        }
        const listaHoras = b.siguientes.map(x => `<strong>${x.hora}</strong>`).join(' · ');
        const icono = linNom === "TREN" ? "🚆" : "⏱";
        const nombreMostrado = linNom === "TREN" ? "Tren" : linNom;
        html += `
          <div style="margin-bottom:4px;">
            ${icono} <strong>${nombreMostrado} (${b.sentidoLabel}):</strong> <span style="color:#0e6287; font-weight:800;">${textoEnCuanto}</span><br>
            <span style="color:#555; font-size:10.5px;">📅 Horarios (${info.etiquetaDia}): ${listaHoras}</span>
          </div>
        `;
      });
      if (incluirBoton) {
        html += `<button class="btn-jump-sched" onclick="irALaPlanillaAbajo()">📅 Ver zona resaltada en planilla ▾</button>`;
      }
      html += `</div>`;
      return html;
    }

    const SEMAFOROS = [
      [-38.9444, -68.2304], [-38.9444, -68.2257], [-38.9506, -68.2258], [-38.9559, -68.2378],
      [-38.9569, -68.2263], [-38.9557, -68.2180], [-38.9556, -68.1969], [-38.9558, -68.1845],
      [-38.9564, -68.1676], [-38.9578, -68.1552], [-38.9579, -68.1401], [-38.9581, -68.1281],
      [-38.9591, -68.1172], [-38.9592, -68.1065], [-38.9594, -68.0935], [-38.9595, -68.0843],
      [-38.9582, -68.0748], [-38.9582, -68.0665], [-38.9582, -68.0590], [-38.9508, -68.0561]
    ];

    function distMts(lat1, lon1, lat2, lon2) {
      const dLat = (lat1 - lat2) * 111139;
      const dLon = (lon1 - lon2) * 111139 * 0.777;
      return Math.sqrt(dLat * dLat + dLon * dLon);
    }

    function densificarPolilinea(pts) {
      if (!pts || pts.length < 2) return pts || [];
      const res = [pts[0]];
      for (let i = 0; i < pts.length - 1; i++) {
        const p1 = pts[i], p2 = pts[i + 1];
        const d = distMts(p1[0], p1[1], p2[0], p2[1]);
        const pasos = Math.max(1, Math.ceil(d / 18));
        for (let s = 1; s <= pasos; s++) {
          const t = s / pasos;
          res.push([p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t]);
        }
      }
      return res;
    }

    function encontrarIndiceMasCercano(lat, lon, pts, idxHint = null) {
      if (!pts || pts.length === 0) return { index: 0, dist: Infinity };
      if (idxHint !== null && idxHint >= 0 && idxHint < pts.length) {
        const ini = Math.max(0, idxHint - 4);
        const fin = Math.min(pts.length - 1, idxHint + 28);
        let minLocalIdx = idxHint, minLocalDist = Infinity;
        for (let i = ini; i <= fin; i++) {
          const d = distMts(lat, lon, pts[i][0], pts[i][1]);
          if (d < minLocalDist) {
            minLocalDist = d;
            minLocalIdx = i;
          }
        }
        if (minLocalDist <= DIST_MAX_EN_RUTA_MTS * 2) {
          return { index: minLocalIdx, dist: minLocalDist };
        }
      }

      let minIdx = 0, minDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = distMts(lat, lon, pts[i][0], pts[i][1]);
        if (d < minDist) {
          minDist = d;
          minIdx = i;
        }
      }
      return { index: minIdx, dist: minDist };
    }

    function interpolarSobreTraza(traza, latA, lonA, latB, lonB, frac) {
      if (!traza || traza.length < 2) {
        return [latA + (latB - latA) * frac, lonA + (lonB - lonA) * frac];
      }
      const posA = encontrarIndiceMasCercano(latA, lonA, traza);
      const posB = encontrarIndiceMasCercano(latB, lonB, traza);
      if (posB.index <= posA.index) {
        return [latA + (latB - latA) * frac, lonA + (lonB - lonA) * frac];
      }
      const idxFloat = posA.index + (posB.index - posA.index) * Math.max(0, Math.min(1, frac));
      const idxBase = Math.floor(idxFloat);
      const idxSig = Math.min(posB.index, idxBase + 1);
      const resto = idxFloat - idxBase;
      const p1 = traza[idxBase], p2 = traza[idxSig];
      return [p1[0] + (p2[0] - p1[0]) * resto, p1[1] + (p2[1] - p1[1]) * resto];
    }

    function actualizarEtiquetaSuperior(trenEnCirculacion = false) {
      const label = document.getElementById('bus-count');
      const txtTren = trenEnCirculacion ? " · 🚆 Tren en recorrido" : " · 🚆 Tren en cabecera";
      if (totalBusesRadar > 0) {
        label.innerText = `🚌 ${totalBusesEnVivo} colectivos activos (${totalBusesRadar} en radar)${txtTren}`;
      } else {
        label.innerText = `Buscando colectivos GPS...${txtTren}`;
      }
    }

    function extraerTramoTren(fila, iniCol, finCol, sentidoCode, sentidoTexto) {
      const paradas = [];
      for (let c = iniCol; c <= finCol; c++) {
        const val = fila[c];
        if (!val || val === "-") continue;
        const stKey = MAPA_COL_ESTACION_TREN[c];
        const stObj = PUNTOS_CONTROL_OFICIALES.find(p => p.key === stKey);
        if (!stObj) continue;
        paradas.push({
          col: c,
          key: stKey,
          nombre: stObj.nombreOficial,
          lat: stObj.lat,
          lon: stObj.lon,
          hora: val,
          min: hhmmAMinutos(val)
        });
      }
      if (paradas.length < 2) return null;
      return {
        sentido_code: sentidoCode,
        sentido: sentidoTexto,
        paradas: paradas,
        minSalida: paradas[0].min,
        minLlegada: paradas[paradas.length - 1].min,
        origen: paradas[0],
        destino: paradas[paradas.length - 1]
      };
    }

    function generarHTMLPopupTren(t) {
      const colorSentido = t.sentido_code === 'HACIA_NEUQUEN' ? '#89DCEB' : '#A6E3A1';
      let estadoHTML = '';
      if (t.estado === 'EN_MOVIMIENTO') {
        estadoHTML = `<div style="color:#117a65; font-weight:800; margin-top:4px;">🟢 En circulación por vía férrea</div>`;
      } else if (t.estado === 'EN_ESTACION') {
        estadoHTML = `<div style="color:#d35400; font-weight:800; margin-top:4px;">🚉 Detenido en ${t.estacionActual}</div>`;
      } else {
        estadoHTML = `<div style="color:#b7950b; font-weight:800; margin-top:4px;">⏸ En ${t.estacionActual}<br><span style="font-weight:normal; font-size:11px; color:#555;">${t.detalleCabecera}</span></div>`;
      }

      return `
        <div style="font-family:sans-serif; font-size:12px; min-width:205px;">
          <div class="stop-popup-badge-train">🚆 Servicio Ferroviario Oficial</div>
          <div style="font-size:14px; font-weight:800; color:#111;">Tren del Valle</div>
          <span style="color:${colorSentido}; background:#181825; padding:1px 6px; border-radius:4px; font-weight:800; font-size:11px; display:inline-block; margin-top:2px;">${t.sentido}</span>
          ${estadoHTML}
          <div style="margin-top:6px; padding-top:5px; border-top:1px solid #ddd; font-size:11.5px; color:#222;">
            📍 <strong>Próxima Estación:</strong><br>
            <span style="font-weight:800; color:#0e6287;">${t.proximaEstacion}</span><br>
            ⏱ <strong>Llegada estimada:</strong> <span style="color:#117a65; font-weight:900;">${t.tiempoProximaTxt}</span> (${t.horaProxima})
          </div>
          <div style="margin-top:4px; font-size:10.5px; color:#555;">
            🏁 Cabecera destino: <strong>${t.destinoNombre}</strong> (${t.horaDestino})
          </div>
          <button class="btn-jump-sched" onclick="desplegarPlanillaConZona('${t.proximaKey}', 'TREN'); irALaPlanillaAbajo();">📅 Ver horarios del Tren en planilla ▾</button>
        </div>
      `;
    }

    function actualizarTrenDelValleEnVivo() {
      const planilla = PLANILLAS_INDALO["TREN_HABIL"];
      if (!planilla || !planilla.filas) return;

      const infoTiempo = obtenerMinutosActualesArgentina();
      const minExacto = infoTiempo.minExacto;
      const esDiaHabil = infoTiempo.sufijoCalendario === "HABIL";

      const tramosActivos = [];

      if (esDiaHabil) {
        planilla.filas.forEach((fila, rIdx) => {
          const tramoIda = extraerTramoTren(fila, 0, 8, "HACIA_NEUQUEN", "Hacia Neuquén / Cipolletti");
          const tramoVta = extraerTramoTren(fila, 8, 16, "HACIA_PLOTTIER", "Hacia Plottier");

          [tramoIda, tramoVta].forEach((tramo, idxDir) => {
            if (!tramo) return;
            // Activo desde 4 minutos antes de salir hasta 1 minuto después de llegar
            if (minExacto >= tramo.minSalida - 4 && minExacto <= tramo.minLlegada + 1) {
              const idTren = `TREN_${rIdx}_${idxDir}`;
              const traza = (RUTAS_DENSAS["TREN"] && RUTAS_DENSAS["TREN"][tramo.sentido_code]) || [];

              if (minExacto < tramo.minSalida) {
                const segFaltan = Math.max(1, Math.ceil(tramo.minSalida - minExacto));
                const prox = tramo.paradas[1];
                const minAProx = Math.max(1, Math.round(prox.min - minExacto));
                tramosActivos.push({
                  id: idTren,
                  lat: tramo.origen.lat,
                  lon: tramo.origen.lon,
                  sentido: tramo.sentido,
                  sentido_code: tramo.sentido_code,
                  estado: "CABECERA",
                  estacionActual: tramo.origen.nombre,
                  detalleCabecera: `Sale en ${segFaltan} min (${tramo.origen.hora})`,
                  proximaEstacion: prox.nombre,
                  proximaKey: prox.key,
                  horaProxima: prox.hora,
                  tiempoProximaTxt: `en ${minAProx} min`,
                  destinoNombre: tramo.destino.nombre,
                  horaDestino: tramo.destino.hora
                });
              } else {
                let segIdx = tramo.paradas.length - 2;
                for (let k = 0; k < tramo.paradas.length - 1; k++) {
                  if (minExacto >= tramo.paradas[k].min && minExacto <= tramo.paradas[k + 1].min) {
                    segIdx = k;
                    break;
                  }
                }
                const pA = tramo.paradas[segIdx];
                const pB = tramo.paradas[segIdx + 1];
                const duracionSeg = Math.max(1, pB.min - pA.min);
                const transcurrido = Math.max(0, Math.min(duracionSeg, minExacto - pA.min));
                const frac = transcurrido / duracionSeg;
                const coords = interpolarSobreTraza(traza, pA.lat, pA.lon, pB.lat, pB.lon, frac);
                const minRestantes = Math.max(0, pB.min - minExacto);
                const enEstacion = transcurrido < 0.40;

                tramosActivos.push({
                  id: idTren,
                  lat: coords[0],
                  lon: coords[1],
                  sentido: tramo.sentido,
                  sentido_code: tramo.sentido_code,
                  estado: enEstacion ? "EN_ESTACION" : "EN_MOVIMIENTO",
                  estacionActual: pA.nombre,
                  detalleCabecera: "",
                  proximaEstacion: pB.nombre,
                  proximaKey: pB.key,
                  horaProxima: pB.hora,
                  tiempoProximaTxt: minRestantes < 0.9 ? "Llegando (< 1 min)" : `en ${Math.ceil(minRestantes)} min`,
                  destinoNombre: tramo.destino.nombre,
                  horaDestino: tramo.destino.hora
                });
              }
            }
          });
        });
      }

      const hayTrenCirculando = tramosActivos.length > 0;

      // Si no hay tren circulando en este minuto, mostramos la formación en Estación Plottier con su próxima salida
      if (!hayTrenCirculando) {
        const estPlo = PUNTOS_CONTROL_OFICIALES.find(p => p.key === "TREN_PLOTTIER");
        const estConst = PUNTOS_CONTROL_OFICIALES.find(p => p.key === "TREN_CONSTITUYENTES");
        const infoProg = calcularHorariosPuntoOficial("TREN_PLOTTIER", "TREN");
        const bloqueSalida = infoProg && infoProg.bloques ? infoProg.bloques[0] : null;
        const horaSal = bloqueSalida ? bloqueSalida.proximo.hora : "05:55";
        const minSal = bloqueSalida ? bloqueSalida.proximo.enMin : 0;

        let detalleEspera = "Opera de lunes a viernes hábiles";
        let txtProx = `Próx. salida ${horaSal}`;
        if (esDiaHabil && minSal > 0) {
          const hs = Math.floor(minSal / 60);
          const ms = minSal % 60;
          detalleEspera = hs > 0
            ? `Próxima salida: ${horaSal} (en ${hs}h ${ms}m)`
            : `Próxima salida: ${horaSal} (en ${ms} min)`;
          txtProx = `a los 7 min de salir (${sumarMinutos(horaSal, 7)})`;
        }

        if (estPlo && estConst) {
          tramosActivos.push({
            id: "TREN_CABECERA_FIJA",
            lat: estPlo.lat,
            lon: estPlo.lon,
            sentido: "Hacia Neuquén / Cipolletti",
            sentido_code: "HACIA_NEUQUEN",
            estado: "CABECERA",
            estacionActual: estPlo.nombreOficial,
            detalleCabecera: detalleEspera,
            proximaEstacion: estConst.nombreOficial,
            proximaKey: "TREN_CONSTITUYENTES",
            horaProxima: sumarMinutos(horaSal, 7),
            tiempoProximaTxt: txtProx,
            destinoNombre: "Estación Neuquén / Cipolletti",
            horaDestino: sumarMinutos(horaSal, 52)
          });
        }
      }

      const idsActivos = new Set();
      tramosActivos.forEach(t => {
        idsActivos.add(t.id);
        const esCabecera = t.estado === "CABECERA";
        const claseExtra = esCabecera ? "bus-cabecera" : "";
        const iconoHtml = `<div class="bus-marker bus-marker-tren ${claseExtra}">🚆 TREN</div>`;
        const iconObj = L.divIcon({
          className: 'custom-icon-tren',
          html: iconoHtml,
          iconSize: [76, 24],
          iconAnchor: [38, 12]
        });

        if (trenesSim[t.id]) {
          const simT = trenesSim[t.id];
          Object.assign(simT, t);
          simT.marker.setLatLng([t.lat, t.lon]);
          if (simT.ultimoEstado !== t.estado) {
            simT.ultimoEstado = t.estado;
            simT.marker.setIcon(iconObj);
          }
          if (simT.marker.isPopupOpen()) {
            simT.marker.getPopup().setContent(generarHTMLPopupTren(simT));
          }
        } else {
          const simT = { ...t, ultimoEstado: t.estado };
          const m = L.marker([t.lat, t.lon], { icon: iconObj, zIndexOffset: 1100 });
          m.bindPopup(() => generarHTMLPopupTren(simT));
          m.on('popupopen', () => {
            m.getPopup().setContent(generarHTMLPopupTren(simT));
            mostrarRuta("TREN", simT.sentido_code);
          });
          m.addTo(map);
          simT.marker = m;
          trenesSim[t.id] = simT;
        }
      });

      for (const id in trenesSim) {
        if (!idsActivos.has(id)) {
          map.removeLayer(trenesSim[id].marker);
          delete trenesSim[id];
        }
      }

      actualizarEtiquetaSuperior(hayTrenCirculando);
    }

    function estaEnRutaProgramada(lat, lon, linea, sentidoCode) {
      const traza = (RUTAS_DENSAS[linea] && RUTAS_DENSAS[linea][sentidoCode]) || [];
      if (traza.length < 2) return false;
      const info = encontrarIndiceMasCercano(lat, lon, traza);
      return info.dist <= DIST_MAX_EN_RUTA_MTS;
    }

    function deslizarMarcador(bus, destLat, destLon, forzar = false) {
      const from = bus.marker.getLatLng();
      const to = L.latLng(destLat, destLon);
      const dist = from.distanceTo(to);
      if (dist < 1) {
        bus.simLat = destLat;
        bus.simLon = destLon;
        return;
      }
      if (dist > 2500) {
        bus.marker.setLatLng(to);
        bus.simLat = destLat;
        bus.simLon = destLon;
        return;
      }

      let start = null;
      const duration = 950;
      const tokenAnim = (bus._animToken || 0) + 1;
      bus._animToken = tokenAnim;

      function step(timestamp) {
        if (bus._animToken !== tokenAnim) return;
        if (!forzar && bus.enRuta) return;
        if (!start) start = timestamp;
        const progress = Math.min((timestamp - start) / duration, 1);
        const lat = from.lat + (to.lat - from.lat) * progress;
        const lon = from.lng + (to.lng - from.lng) * progress;
        bus.simLat = lat;
        bus.simLon = lon;
        bus.marker.setLatLng([lat, lon]);
        if (progress < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }

    function calcularProximaParada(bus) {
      const mapaOrden = ORDEN_PARADAS_OFICIALES[bus.linea] || ORDEN_PARADAS_OFICIALES["DEFAULT"] || {};
      const clavesOrden = mapaOrden[bus.sentido_code] || (ORDEN_PARADAS_OFICIALES["DEFAULT"] && ORDEN_PARADAS_OFICIALES["DEFAULT"]["HACIA_PLOTTIER"]) || [];
      const paradasRuta = clavesOrden
        .map(k => PUNTOS_CONTROL_OFICIALES.find(p => p.key === k))
        .filter(Boolean);

      if (paradasRuta.length === 0) return "Avanzando en recorrido";

      const traza = (RUTAS_DENSAS[bus.linea] && RUTAS_DENSAS[bus.linea][bus.sentido_code]) || [];

      if (traza.length > 2) {
        const posBus = encontrarIndiceMasCercano(bus.simLat, bus.simLon, traza, bus.trazaIdx);
        let mejorParada = null;
        let mejorIdxStop = Infinity;

        for (let i = 0; i < paradasRuta.length; i++) {
          const pc = paradasRuta[i];
          if (i === 0 && paradasRuta.length > 1) continue;
          const posStop = encontrarIndiceMasCercano(pc.lat, pc.lon, traza);
          if (posStop.index > posBus.index + 2 && posStop.index < mejorIdxStop) {
            mejorIdxStop = posStop.index;
            mejorParada = pc;
          }
        }

        if (mejorParada) {
          let distRecorridoMts = 0;
          for (let k = posBus.index; k < mejorIdxStop; k++) {
            distRecorridoMts += distMts(traza[k][0], traza[k][1], traza[k + 1][0], traza[k + 1][1]);
          }
          const velMps = Math.max(5.5, (bus.vel_kmh || 32) / 3.6);
          const minEst = Math.max(1, Math.round((distRecorridoMts / velMps) / 60));
          return `${mejorParada.nombreOficial} (~${minEst} min)`;
        }
      }

      const haciaNqn = bus.sentido_code === "HACIA_NEUQUEN";
      let mejorParadaFallback = null;
      let menorDist = Infinity;

      for (let i = 1; i < paradasRuta.length; i++) {
        const pc = paradasRuta[i];
        const deltaLon = pc.lon - bus.simLon;
        if (haciaNqn && deltaLon < -0.002) continue;
        if (!haciaNqn && deltaLon > 0.002) continue;
        const d = distMts(bus.simLat, bus.simLon, pc.lat, pc.lon);
        if (d > 60 && d < menorDist) {
          menorDist = d;
          mejorParadaFallback = pc;
        }
      }

      if (!mejorParadaFallback) {
        mejorParadaFallback = paradasRuta[paradasRuta.length - 1];
        menorDist = distMts(bus.simLat, bus.simLon, mejorParadaFallback.lat, mejorParadaFallback.lon);
      }

      const velMps = Math.max(5.5, (bus.vel_kmh || 32) / 3.6);
      const minEst = Math.max(1, Math.round(((menorDist * 1.25) / velMps) / 60));
      return `${mejorParadaFallback.nombreOficial} (~${minEst} min)`;
    }

    async function init() {
      map = L.map('map', { zoomControl: false }).setView([-38.955, -68.15], 12);
      L.control.zoom({ position: 'topright' }).addTo(map);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

      capaRuta = L.layerGroup().addTo(map);
      capaParadas = L.layerGroup().addTo(map);

      const r = await fetch('/api/static_data');
      const staticData = await r.json();
      RUTAS_GEO = staticData.trazas || {};

      const horariosJson = staticData.horarios_oficiales || {};
      PUNTOS_CONTROL_OFICIALES = horariosJson.puntos_control || [];
      ORDEN_PARADAS_OFICIALES = horariosJson.orden_paradas || {};
      PLANILLAS_INDALO = horariosJson.planillas || {};

      if (horariosJson.traza_tren) {
        RUTAS_GEO["TREN"] = horariosJson.traza_tren;
      }

      const infoHoy = obtenerMinutosActualesArgentina();
      clavePlanillaActual = resolverClavePlanilla("50A", infoHoy.sufijoDia);

      for (const [lin, sentidos] of Object.entries(RUTAS_GEO)) {
        RUTAS_DENSAS[lin] = {};
        for (const [sent, pts] of Object.entries(sentidos)) {
          RUTAS_DENSAS[lin][sent] = densificarPolilinea(pts);
        }
      }

      dibujarParadas(staticData.paradas);
      actualizarTrenDelValleEnVivo();
      setInterval(actualizarTrenDelValleEnVivo, 3000);
      pedirDatos();
      setInterval(pedirDatos, 9000);
      requestAnimationFrame(loopFisicoContinuo);
    }

    function dibujarParadas(paradas) {
      capaParadas.clearLayers();

      const mapaDestacadas = {};
      PUNTOS_CONTROL_OFICIALES.forEach(pc => {
        let mejorIdx = -1, menorD = 60;
        paradas.forEach((p, idx) => {
          const esParadaTren = Boolean(p[4] && p[4]["TREN"]);
          if (pc.soloTren) {
            if (p[0] === pc.key) mejorIdx = idx;
          } else if (!esParadaTren) {
            const d = distMts(pc.lat, pc.lon, p[1], p[2]);
            if (d < menorD) {
              menorD = d;
              mejorIdx = idx;
            }
          }
        });
        if (mejorIdx !== -1) {
          mapaDestacadas[mejorIdx] = pc;
        }
      });

      paradas.forEach((p, idx) => {
        const id = p[0], lat = p[1], lon = p[2], desc = p[3], lineas = p[4];
        const puntoOficial = mapaDestacadas[idx] || null;
        const esEstacionTren = Boolean(puntoOficial && puntoOficial.soloTren);
        const pKey = puntoOficial ? puntoOficial.key : "";

        const ordenBotones = ["50A", "50B", "50R", "URBANO", "52 CENTRO", "52 UNION"];
        const clavesLineas = Object.keys(lineas).filter(k => k !== "TREN").sort((a, b) => {
          const ia = ordenBotones.indexOf(a), ib = ordenBotones.indexOf(b);
          return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
        });

        let botones = '';
        if (esEstacionTren) {
          botones += `<button class="btn-query-stop" onclick="mostrarRuta('TREN', 'HACIA_NEUQUEN')">🛤️ Trazado Vía Férrea</button>`;
        } else {
          for (const linNom of clavesLineas) {
            const info = lineas[linNom];
            botones += `<button class="btn-query-stop" onclick="consultarParada(this, '${info.parada}', '${info.cod}', '${linNom}', '${pKey}')">⏱ ${linNom}</button>`;
          }
        }

        let marker;
        if (esEstacionTren) {
          const iconoTrenPin = L.divIcon({
            className: 'custom-stop-train',
            html: `<div class="stop-train-pin" title="${puntoOficial.nombreOficial}">🚆</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12]
          });
          marker = L.marker([lat, lon], { icon: iconoTrenPin, zIndexOffset: 950 });
        } else if (puntoOficial) {
          const iconoDestacado = L.divIcon({
            className: 'custom-stop-featured',
            html: `<div class="stop-featured-pin" title="${puntoOficial.nombreOficial}">✓</div>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
          });
          marker = L.marker([lat, lon], { icon: iconoDestacado, zIndexOffset: 900 });
        } else {
          marker = L.circleMarker([lat, lon], {
            radius: 3.0, color: '#FAB387', fillColor: '#F9E2AF', fillOpacity: 0.65, weight: 1.0
          });
        }

        const tituloPopup = esEstacionTren
          ? `🚆 ${puntoOficial.nombreOficial}`
          : (puntoOficial ? `✅ ${puntoOficial.nombreOficial}` : `📍 ${desc}`);
        const badgeOficial = esEstacionTren
          ? `<div class="stop-popup-badge-train">🚆 Estación Oficial Tren del Valle</div>`
          : (puntoOficial ? `<div class="stop-popup-badge">✓ Parada Oficial de Planilla</div>` : '');

        marker.bindPopup(`
          <div class="stop-popup-wrap" style="min-width:205px;">
            ${badgeOficial}
            <div class="stop-popup-title">${tituloPopup}</div>
            <div class="stop-popup-desc">Ref: ${id}</div>
            <div>${botones}</div>
            <div class="result-box" style="display:none;"></div>
          </div>
        `);

        if (puntoOficial) {
          marker.on('popupopen', (e) => {
            const linInicial = esEstacionTren
              ? "TREN"
              : (lineas["50A"] ? "50A" : (lineas["50B"] ? "50B" : (lineas["50R"] ? "50R" : null)));
            desplegarPlanillaConZona(pKey, linInicial);

            const popupNode = e.popup.getElement();
            if (!popupNode) return;
            const box = popupNode.querySelector('.result-box');
            if (!box) return;

            let resumenProg = '';
            const listaEval = esEstacionTren ? ["TREN"] : ["50A", "50B", "50R"];
            listaEval.forEach(lNom => {
              if (lineas[lNom] || obtenerColsPuntoSegunLinea(puntoOficial, lNom).length > 0) {
                resumenProg += armarHTMLHorarioProgramado(pKey, lNom, false);
              }
            });

            if (resumenProg) {
              resumenProg += `<button class="btn-jump-sched" onclick="irALaPlanillaAbajo()">📅 Ver zona resaltada en planilla ▾</button>`;
              box.style.display = 'block';
              const encabezadoBox = esEstacionTren
                ? `<div style="font-size:10.5px; color:#555; margin-bottom:2px;">Próximos servicios ferroviarios:</div>`
                : `<div style="font-size:10.5px; color:#555; margin-bottom:2px;">Toque una línea arriba para buscar GPS en vivo:</div>`;
              box.innerHTML = encabezadoBox + resumenProg;
            }
          });
        }

        capaParadas.addLayer(marker);
      });
    }

    async function consultarParada(btnEl, idParada, codLinea, linNom, puntoKey) {
      const wrap = btnEl ? btnEl.closest('.stop-popup-wrap') : null;
      const box = wrap ? wrap.querySelector('.result-box') : document.querySelector('.leaflet-popup-content .result-box');

      if (puntoKey && (linNom === "50A" || linNom === "50B" || linNom === "50R" || linNom === "TREN")) {
        desplegarPlanillaConZona(puntoKey, linNom);
      }

      const progHTML = puntoKey ? armarHTMLHorarioProgramado(puntoKey, linNom, true) : '';

      if (box) {
        box.style.display = 'block';
        box.innerHTML = `<em>Consultando GPS en vivo de ${linNom}...</em>${progHTML}`;
      }

      try {
        const r = await fetch(`/api/parada?id=${encodeURIComponent(idParada)}&cod=${encodeURIComponent(codLinea)}&linea=${encodeURIComponent(linNom)}`);
        const data = await r.json();
        if (!data.arribos || data.arribos.length === 0) {
          if (box) {
            box.innerHTML = `
              <div style="color:#666;">Sin unidades cercanas reportando GPS en vivo.</div>
              ${progHTML}
            `;
          }
        } else {
          let h = '';
          data.arribos.forEach(a => {
            h += `<div style="margin-bottom:3px;"><strong>${a.ramal}</strong> (${a.sentido})<br>Arribo GPS: <span style="color:#27ae60; font-weight:bold;">${a.tiempo}</span></div>`;
          });
          h += progHTML;
          if (box) box.innerHTML = h;
          pedirDatos();
        }
      } catch (e) {
        if (box) box.innerHTML = `<div style="color:#c0392b;">Error al conectar con GPS en vivo.</div>${progHTML}`;
      }
    }

    function generarHTMLPopup(bus) {
      const colorSentido = bus.sentido_code === 'HACIA_NEUQUEN' ? '#FAB387' : '#A6E3A1';
      let estadoHTML = '';

      if (bus.cabecera && bus.edad_senal >= LIMITE_DEBIL_SEG) {
        estadoHTML = `<div style="color:#b7950b; font-weight:700; margin-top:4px;">⏸ En ${bus.cabecera}<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad aguardando horario de salida</span></div>`;
      } else if (bus.edad_senal > LIMITE_AVERIA_SEG) {
        const minSin = Math.floor(bus.edad_senal / 60);
        estadoHTML = `<div style="color:#c0392b; font-weight:700; margin-top:4px;">🚨 Sin señal (${minSin} min)<br><span style="font-weight:normal; font-size:11px; color:#555;">Unidad detenida hasta recuperar señal</span></div>`;
      } else if (bus.edad_senal >= LIMITE_DEBIL_SEG) {
        const minDebil = Math.floor(bus.edad_senal / 60);
        const segDebil = Math.round(bus.edad_senal % 60);
        estadoHTML = `<div style="color:#d35400; font-weight:700; margin-top:4px;">⚠️ Señal débil (${minDebil}m ${segDebil}s)<br><span style="font-weight:normal; font-size:11px; color:#555;">Estimando avance sobre el recorrido</span></div>`;
      } else if (bus.enSemaforo && bus.enRuta) {
        estadoHTML = `<div style="color:#e67e22; font-weight:700; margin-top:4px;">🚦 Detenido en semáforo</div>`;
      } else {
        estadoHTML = `<div style="color:#27ae60; font-weight:700; margin-top:4px;">🟢 En movimiento (~${Math.round(bus.vel_kmh || 34)} km/h)</div>`;
      }

      const proxParada = calcularProximaParada(bus);

      return `
        <div style="font-family:sans-serif; font-size:12px; min-width:180px;">
          <strong style="font-size:14px;">Línea ${bus.linea}</strong>
          <span style="color:#666; font-size:11px;">(${bus.ramal})</span><br>
          <span style="color:${colorSentido}; font-weight:800;">${bus.sentido}</span>
          ${estadoHTML}
          <div style="margin-top:5px; padding-top:4px; border-top:1px solid #ddd; font-size:11px; color:#222;">
            📍 <strong>Próxima Parada Oficial:</strong><br>${proxParada}
          </div>
        </div>
      `;
    }

    function obtenerEstadoVisual(bus) {
      if (bus.cabecera && bus.edad_senal >= LIMITE_DEBIL_SEG) return "CABECERA";
      if (bus.edad_senal > LIMITE_AVERIA_SEG) return "AVERIA";
      if (bus.edad_senal >= LIMITE_DEBIL_SEG) return "DEBIL";
      return "NORMAL";
    }

    function construirIcono(bus) {
      let clase = "bus-marker-50b";
      if (bus.linea === "50A") clase = "bus-marker-50a";
      if (bus.linea === "50R") clase = "bus-marker-50r";
      if (bus.linea === "URBANO") clase = "bus-marker-urbano";
      if (bus.linea.includes("52")) clase = "bus-marker-52";

      const est = obtenerEstadoVisual(bus);
      let estadoClase = "";
      let iconoPrefijo = "🚌";
      if (est === "CABECERA") {
        estadoClase = "bus-cabecera";
        iconoPrefijo = "⏸️";
      } else if (est === "AVERIA") {
        estadoClase = "bus-stalled";
        iconoPrefijo = "🚨";
      } else if (est === "DEBIL") {
        estadoClase = "bus-weak";
        iconoPrefijo = "📡";
      }

      return L.divIcon({
        className: 'custom-icon',
        html: `<div class="bus-marker ${clase} ${estadoClase}">${iconoPrefijo} ${bus.linea}</div>`,
        iconSize: [72, 24],
        iconAnchor: [36, 12]
      });
    }

    let ultimoFrame = performance.now();
    function loopFisicoContinuo(ahoraMs) {
      const dt = Math.min((ahoraMs - ultimoFrame) / 1000.0, 0.25);
      ultimoFrame = ahoraMs;

      for (const id in busesSim) {
        const b = busesSim[id];

        b.edad_senal += dt;

        const nuevoEst = obtenerEstadoVisual(b);
        if (b.estadoVisual !== nuevoEst) {
          b.estadoVisual = nuevoEst;
          b.marker.setIcon(construirIcono(b));
        }

        if (!b.enRuta) {
          b.enSemaforo = false;
          continue;
        }

        if ((b.cabecera && b.edad_senal >= LIMITE_DEBIL_SEG) || b.edad_senal > LIMITE_AVERIA_SEG) {
          continue;
        }

        if (distMts(b.simLat, b.simLon, b.gpsLat, b.gpsLon) > 220) {
          continue;
        }

        if (b.pausaHastaMs && ahoraMs < b.pausaHastaMs) {
          b.enSemaforo = true;
          continue;
        } else {
          b.enSemaforo = false;
        }

        for (let s = 0; s < SEMAFOROS.length; s++) {
          const sem = SEMAFOROS[s];
          if (distMts(b.simLat, b.simLon, sem[0], sem[1]) < 20) {
            if (b.ultimoSemaforoIdx !== s) {
              b.ultimoSemaforoIdx = s;
              if (Math.random() < 0.45) {
                b.pausaHastaMs = ahoraMs + (7000 + Math.random() * 6000);
                b.enSemaforo = true;
                break;
              }
            }
          }
        }
        if (b.enSemaforo) continue;

        const factorSenal = b.edad_senal >= LIMITE_DEBIL_SEG ? 0.60 : 0.85;
        const velMps = ((b.vel_kmh || 32) / 3.6) * factorSenal;
        let avanceMts = velMps * dt;

        const traza = (RUTAS_DENSAS[b.linea] && RUTAS_DENSAS[b.linea][b.sentido_code]) || [];
        if (traza.length < 2) continue;

        const infoCercana = encontrarIndiceMasCercano(b.simLat, b.simLon, traza, b.trazaIdx);
        if (infoCercana.dist > DIST_MAX_EN_RUTA_MTS) {
          b.enRuta = false;
          continue;
        }

        let idx = infoCercana.index;
        while (avanceMts > 0 && idx < traza.length - 1) {
          const sig = traza[idx + 1];
          const dSeg = distMts(b.simLat, b.simLon, sig[0], sig[1]);
          if (dSeg <= avanceMts) {
            b.simLat = sig[0];
            b.simLon = sig[1];
            avanceMts -= dSeg;
            idx++;
          } else {
            const frac = avanceMts / dSeg;
            b.simLat += (sig[0] - b.simLat) * frac;
            b.simLon += (sig[1] - b.simLon) * frac;
            avanceMts = 0;
          }
        }
        b.trazaIdx = idx;

        b.marker.setLatLng([b.simLat, b.simLon]);
      }

      requestAnimationFrame(loopFisicoContinuo);
    }

    function mostrarRuta(linea, sentidoCode) {
      capaRuta.clearLayers();
      if (!RUTAS_GEO[linea] || !RUTAS_GEO[linea][sentidoCode]) return;

      if (linea === "TREN") {
        // Doble traza estilo vía férrea (base oscura + riel discontinuo celeste)
        capaRuta.addLayer(L.polyline(RUTAS_GEO["TREN"][sentidoCode], { color: "#112A38", weight: 7, opacity: 0.95 }));
        capaRuta.addLayer(L.polyline(RUTAS_GEO["TREN"][sentidoCode], { color: "#89DCEB", weight: 3, opacity: 1.0, dashArray: "8, 6" }));
      } else {
        let color = "#89B4FA";
        if (linea === "50A") color = "#A6E3A1";
        if (linea === "50R") color = "#CBA6F7";
        if (linea === "URBANO") color = "#F9E2AF";
        if (linea.includes("52")) color = "#FAB387";
        capaRuta.addLayer(L.polyline(RUTAS_GEO[linea][sentidoCode], { color: color, weight: 5, opacity: 0.9 }));
      }
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
        sincronizarBuses(d.buses);
      } catch (e) {}
    }

    function sincronizarBuses(buses) {
      totalBusesRadar = buses.length;
      totalBusesEnVivo = buses.filter(b => b.edad_senal <= LIMITE_AVERIA_SEG).length;
      actualizarTrenDelValleEnVivo();

      const idsActivos = new Set();

      buses.forEach(b => {
        idsActivos.add(b.id);
        const dentroDeRuta = estaEnRutaProgramada(b.lat, b.lon, b.linea, b.sentido_code);

        if (busesSim[b.id]) {
          const sim = busesSim[b.id];
          const saltoGps = distMts(sim.gpsLat, sim.gpsLon, b.lat, b.lon);
          const cambioSentido = sim.sentido_code !== b.sentido_code;

          sim.gpsLat = b.lat;
          sim.gpsLon = b.lon;
          sim.vel_kmh = b.vel_kmh || sim.vel_kmh;
          sim.sentido = b.sentido;
          sim.sentido_code = b.sentido_code;
          sim.ramal = b.ramal;
          sim.cabecera = b.cabecera;
          sim.edad_senal = b.edad_senal;
          sim.enRuta = dentroDeRuta;

          if (!dentroDeRuta) {
            sim.trazaIdx = null;
            deslizarMarcador(sim, b.lat, b.lon, true);
          } else if (saltoGps > 15 || cambioSentido) {
            sim.pausaHastaMs = 0;
            const traza = (RUTAS_DENSAS[b.linea] && RUTAS_DENSAS[b.linea][b.sentido_code]) || [];
            const infoGps = encontrarIndiceMasCercano(b.lat, b.lon, traza, cambioSentido ? null : sim.trazaIdx);
            const infoSim = encontrarIndiceMasCercano(sim.simLat, sim.simLon, traza, sim.trazaIdx);
            const distSimAGps = distMts(sim.simLat, sim.simLon, b.lat, b.lon);

            if (!cambioSentido && infoSim.index >= infoGps.index && distSimAGps < 90) {
              sim.vel_kmh = Math.max(16, (b.vel_kmh || 28) * 0.75);
            } else {
              sim.trazaIdx = infoGps.index;
              deslizarMarcador(sim, b.lat, b.lon, true);
            }
          }

          const nuevoEst = obtenerEstadoVisual(sim);
          if (sim.estadoVisual !== nuevoEst) {
            sim.estadoVisual = nuevoEst;
            sim.marker.setIcon(construirIcono(sim));
          }

          if (sim.marker.isPopupOpen()) {
            sim.marker.getPopup().setContent(generarHTMLPopup(sim));
          }
        } else {
          const trazaIni = (RUTAS_DENSAS[b.linea] && RUTAS_DENSAS[b.linea][b.sentido_code]) || [];
          const infoIni = encontrarIndiceMasCercano(b.lat, b.lon, trazaIni);
          const nuevoSim = {
            ...b,
            simLat: b.lat,
            simLon: b.lon,
            gpsLat: b.lat,
            gpsLon: b.lon,
            trazaIdx: infoIni.index,
            enRuta: dentroDeRuta,
            enSemaforo: false,
            pausaHastaMs: 0,
            ultimoSemaforoIdx: -1,
            estadoVisual: "NORMAL"
          };
          nuevoSim.estadoVisual = obtenerEstadoVisual(nuevoSim);
          const m = L.marker([b.lat, b.lon], { icon: construirIcono(nuevoSim) });
          m.bindPopup(() => generarHTMLPopup(nuevoSim));
          m.on('popupopen', () => {
            m.getPopup().setContent(generarHTMLPopup(nuevoSim));
            mostrarRuta(nuevoSim.linea, nuevoSim.sentido_code);
          });
          m.addTo(map);
          nuevoSim.marker = m;
          busesSim[b.id] = nuevoSim;
        }
      });

      for (let id in busesSim) {
        if (!idsActivos.has(id)) {
          map.removeLayer(busesSim[id].marker);
          delete busesSim[id];
        }
      }
    }

    init();
  </script>
</body>
</html>
"""
