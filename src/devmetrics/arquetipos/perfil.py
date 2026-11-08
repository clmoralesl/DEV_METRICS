"""Perfil como mezcla de arquetipos: funcion pura, sin E/S."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .configuracion import CLASES, Configuracion
from .senales import Senales

DOMINANTE = "dominante"
MIXTO = "mixto"
DATOS_INSUFICIENTES = "datos_insuficientes"
_EPS = 1e-9


@dataclass(frozen=True)
class Perfil:
    puntajes: dict[str, float]
    estado: str
    dominante: str | None
    confianza: str  # baja | media | alta
    tendencia: str | None  # clase con mayor puntaje, aunque no se declare dominante
    margen: float
    evidencia: float  # fuerza bruta de la senal de arquetipo (antes de normalizar)
    eventos_faltantes: int  # actividad adicional para alcanzar el volumen minimo

    def a_dict(self) -> dict:
        return asdict(self)


def _saturar(valor: float, k: float) -> float:
    return valor / (valor + k) if valor > 0 else 0.0


def puntajes_brutos(s: Senales, c: Configuracion) -> dict[str, float]:
    entradas = {
        "infraestructura": s.f_infraestructura,
        "documentacion": s.f_documentacion,
        "frontend": s.f_frontend,
        "pruebas": s.f_pruebas,
        "correccion": s.f_correccion,
        "revisiones": _saturar(s.revisiones, c.saturacion["revisiones"]),
        "comentarios": _saturar(s.comentarios, c.saturacion["comentarios"]),
        "issues": _saturar(s.issues_atendidos, c.saturacion["issues"]),
    }
    return {
        clase: sum(peso * entradas[senal] for senal, peso in c.pesos[clase].items())
        for clase in CLASES
    }


def _confianza(s: Senales, c: Configuracion) -> str:
    if s.volumen >= c.confianza_alta and s.repos > 1:
        return "alta"
    if s.volumen >= c.confianza_media:
        return "media"
    return "baja"


def calcular_perfil(s: Senales, c: Configuracion) -> Perfil:
    brutos = puntajes_brutos(s, c)
    evidencia = sum(brutos.values())
    if evidencia > 0:
        puntajes = {k: v / evidencia for k, v in brutos.items()}
    else:
        puntajes = {k: 1 / len(CLASES) for k in CLASES}  # sin senal: reparto uniforme
    orden = sorted(CLASES, key=lambda k: puntajes[k], reverse=True)
    margen = puntajes[orden[0]] - puntajes[orden[1]]
    tendencia = orden[0] if margen > _EPS else None
    confianza = _confianza(s, c)

    if s.volumen < c.minimo_eventos:
        estado, dominante, confianza = DATOS_INSUFICIENTES, None, "baja"
    elif evidencia < c.evidencia_minima or margen < c.margen_minimo - _EPS:
        estado, dominante = MIXTO, None
    else:
        estado, dominante = DOMINANTE, orden[0]

    return Perfil(
        puntajes=puntajes,
        estado=estado,
        dominante=dominante,
        confianza=confianza,
        tendencia=tendencia,
        margen=margen,
        evidencia=evidencia,
        eventos_faltantes=max(0, c.minimo_eventos - s.volumen),
    )
