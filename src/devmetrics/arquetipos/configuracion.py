"""Configuracion de arquetipos: rutas, palabras, pesos y umbrales sin tocar el codigo."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

CLASES = ("druid", "cleric", "bard")
CATEGORIAS_RUTA = ("pruebas", "documentacion", "infraestructura", "frontend")
TIPOS_CAMBIO = (
    "correccion",
    "funcionalidad",
    "documentacion",
    "infraestructura",
    "refactor",
    "otro",
)


@dataclass(frozen=True)
class Configuracion:
    rutas: dict[str, tuple[re.Pattern, ...]]
    palabras: dict[str, tuple[str, ...]]
    pesos: dict[str, dict[str, float]]
    saturacion: dict[str, float]
    margen_minimo: float
    evidencia_minima: float
    minimo_eventos: int
    confianza_media: int
    confianza_alta: int


def desde_dict(datos: dict) -> Configuracion:
    rutas = {
        cat: tuple(re.compile(p, re.IGNORECASE) for p in patrones)
        for cat, patrones in datos["rutas"].items()
    }
    desconocidas = set(rutas) - set(CATEGORIAS_RUTA)
    if desconocidas:
        raise ValueError(f"categorias de ruta desconocidas: {sorted(desconocidas)}")
    pesos = datos["pesos"]
    if set(pesos) != set(CLASES):
        raise ValueError(f"pesos debe definir exactamente las clases {CLASES}")
    senales_validas = {
        "infraestructura", "documentacion", "frontend", "pruebas",
        "correccion", "revisiones", "comentarios", "issues",
    }  # fmt: skip
    for clase, pesos_clase in pesos.items():
        invalidas = set(pesos_clase) - senales_validas
        if invalidas:
            raise ValueError(f"senales desconocidas en pesos de {clase}: {sorted(invalidas)}")
    if not {"revisiones", "comentarios", "issues"} <= set(datos["saturacion"]):
        raise ValueError("saturacion debe definir revisiones, comentarios e issues")
    u = datos["umbrales"]
    if not 0 <= u["evidencia_minima"] <= 1:
        raise ValueError("evidencia_minima debe estar en [0, 1]")
    if not 0 <= u["margen_minimo"] < 1:
        raise ValueError("margen_minimo debe estar en [0, 1)")
    if not u["minimo_eventos"] <= u["confianza_media"] <= u["confianza_alta"]:
        raise ValueError("se exige minimo_eventos <= confianza_media <= confianza_alta")
    return Configuracion(
        rutas=rutas,
        palabras={k: tuple(v) for k, v in datos["palabras"].items()},
        pesos=pesos,
        saturacion=datos["saturacion"],
        margen_minimo=u["margen_minimo"],
        evidencia_minima=u["evidencia_minima"],
        minimo_eventos=u["minimo_eventos"],
        confianza_media=u["confianza_media"],
        confianza_alta=u["confianza_alta"],
    )


def cargar(ruta: str | Path | None = None) -> Configuracion:
    """Carga la configuracion indicada o la incluida en el paquete."""
    if ruta is None:
        texto = (
            resources.files("devmetrics.arquetipos")
            .joinpath("configuracion_defecto.json")
            .read_text(encoding="utf-8")
        )
    else:
        texto = Path(ruta).read_text(encoding="utf-8")
    return desde_dict(json.loads(texto))
