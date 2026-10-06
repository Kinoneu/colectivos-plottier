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
    (-38.955231, -68.232747, "Estación Plottier (Tren del Valle)"),
    (-38.955890, -68.058250, "Estación Neuquén Central (Tren)"),
    (-38.941903, -67.996640, "Estación Cipolletti (Tren)")
]

# Paradas terminales y nodos de bucle que capturan el 100% de la flota en ambos sentidos
PARADAS_RADAR = [
    ("NV 2574", "1013", "50A"),
    ("NV4120", "1013", "50A"),
    ("NV 2574", "1014", "50B"),
    ("NV4120", "1014", "50B"),
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

TRAZA_VIAL_TREN = [
    [-38.955231, -68.232747], # Estación Plottier
    [-38.955265, -68.225750], # Paso a nivel Av. San Martín (Plottier)
    [-38.955295, -68.218000], # Altura Terminal ETOP
    [-38.955330, -68.196060], # Apeadero Constituyentes
    [-38.955440, -68.186500], # Altura Piscicultura
    [-38.955556, -68.178333], # Apeadero Barrio Unión (Río Limay)
    [-38.955556, -68.167650], # Paso a nivel Río Colorado
    [-38.955556, -68.141111], # Apeadero Aeropuerto (San Martín y Goya)
    [-38.955620, -68.128000], # Paso a nivel Crouzeilles
    [-38.955680, -68.116880], # Apeadero El Cholar
    [-38.955833, -68.105278], # Apeadero ETON (Solalique)
    [-38.955825, -68.093500], # Paso a nivel Gatica
    [-38.955820, -68.079510], # Apeadero Ignacio Rivas
    [-38.955855, -68.066550], # Paso a nivel Laínez
    [-38.955890, -68.058250], # Estación Neuquén Central
    [-38.955915, -68.052150], # Paso a nivel Santa Fe
    [-38.955930, -68.044500], # Paso a nivel Bahía Blanca
    [-38.955650, -68.041000], # Inicio curva ferroviaria Linares / Borlenghi
    [-38.954700, -68.037000], # Curva Tronador / Mariano Moreno
    [-38.952200, -68.030500], # Diagonal Villa Farrell / Primeros Pobladores
    [-38.948800, -68.022500], # Aproximación Río Neuquén
    [-38.946111, -68.016944], # Puente Ferroviario Neuquén-Cipolletti (FC Roca)
    [-38.944500, -68.013000], # Margen Este Río Neuquén
    [-38.943100, -68.006500], # Curva ingreso Cipolletti
    [-38.942350, -68.001000], # Paralelo Av. Gral. Fernández Oro
    [-38.941903, -67.996640]  # Estación Cipolletti
]

TRAZA_TREN_GEO = {
    "HACIA_NEUQUEN": TRAZA_VIAL_TREN,
    "HACIA_PLOTTIER": list(reversed(TRAZA_VIAL_TREN))
}
