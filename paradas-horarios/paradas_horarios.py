import os
import sys
import math

# Asegura que Python encuentre las subcarpetas internas aunque app.py lo cargue dinámicamente
MOD_DIR = os.path.dirname(os.path.abspath(__file__))
if MOD_DIR not in sys.path:
    sys.path.insert(0, MOD_DIR)

from catalogos.radar_y_cabeceras import CABECERAS_GEO, PARADAS_RADAR, TRAZA_TREN_GEO
from catalogos.puntos_y_recorridos import PUNTOS_CONTROL_OFICIALES, ORDEN_PARADAS
from planillas.cronogramas import PLANILLAS_OFICIALES

with open(os.path.join(MOD_DIR, "frontend", "index.html"), "r", encoding="utf-8") as f:
    HTML_COMPLETO = f.read()

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

def obtener_horarios_oficiales():
    return {
        "puntos_control": PUNTOS_CONTROL_OFICIALES,
        "orden_paradas": ORDEN_PARADAS,
        "planillas": PLANILLAS_OFICIALES,
        "traza_tren": TRAZA_TREN_GEO
    }