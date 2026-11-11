"""La documentacion de arquitectura no debe desviarse del repositorio."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DOC = RAIZ / "documentacion" / "arquitectura.md"
SVG = ["arquitectura.svg", "flujo_indexacion.svg", "flujo_consulta.svg"]


def test_los_svg_son_xml_valido_con_titulo():
    for nombre in SVG:
        raiz = ET.parse(RAIZ / "documentacion" / "diagramas" / nombre).getroot()
        assert raiz.tag.endswith("svg") and raiz.get("viewBox")
        assert any(e.tag.endswith("title") and e.text for e in raiz)


def test_el_documento_referencia_cada_diagrama_y_los_enlaces_existen():
    texto = DOC.read_text(encoding="utf-8")
    for nombre in SVG:
        assert f"diagramas/{nombre}" in texto
    for destino in re.findall(r"\]\((diagramas/[^)]+)\)", texto):
        assert (DOC.parent / destino).is_file(), destino


def test_las_rutas_citadas_en_el_documento_existen():
    texto = DOC.read_text(encoding="utf-8")
    rutas = re.findall(r"`((?:src|scripts|prompts|conocimiento)/[^`\s]+)`", texto)
    assert rutas
    for ruta in rutas:
        base = ruta.split("*")[0]
        assert (RAIZ / base).exists(), ruta
