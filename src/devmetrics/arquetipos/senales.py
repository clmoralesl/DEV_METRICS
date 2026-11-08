"""Senales de actividad de un desarrollador, independientes de prefijos de commit."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .configuracion import CATEGORIAS_RUTA, TIPOS_CAMBIO, Configuracion


@dataclass(frozen=True)
class Commit:
    mensaje: str
    archivos: tuple[str, ...] = ()
    repo: str = ""
    tipo_cambio: str | None = None  # si viene dado (p. ej. del LLM), reemplaza a la heuristica


@dataclass(frozen=True)
class Actividad:
    commits: tuple[Commit, ...] = ()
    revisiones: int = 0  # PR ajenos revisados
    comentarios: int = 0  # comentarios en PR e issues ajenos
    issues_atendidos: int = 0


@dataclass(frozen=True)
class Senales:
    n_commits: int = 0
    f_infraestructura: float = 0.0
    f_documentacion: float = 0.0
    f_frontend: float = 0.0
    f_pruebas: float = 0.0
    f_codigo: float = 0.0
    f_correccion: float = 0.0
    revisiones: int = 0
    comentarios: int = 0
    issues_atendidos: int = 0
    repos: int = 0
    categorias_activas: int = 0

    @property
    def volumen(self) -> int:
        return self.n_commits + self.revisiones + self.comentarios + self.issues_atendidos


def categoria_ruta(ruta: str, config: Configuracion) -> str:
    """Primera categoria cuyo patron coincide; si ninguna, 'codigo'."""
    ruta = ruta.replace("\\", "/")
    for categoria in CATEGORIAS_RUTA:
        if any(p.search(ruta) for p in config.rutas.get(categoria, ())):
            return categoria
    return "codigo"


def _tiene_palabra(mensaje: str, palabras: tuple[str, ...]) -> bool:
    # palabra completa con sufijos simples: "fix" y "fixes" si, "fixture" no
    return any(
        re.search(rf"\b{re.escape(p)}(e[sd]|ing|s)?\b", mensaje, re.IGNORECASE) for p in palabras
    )


def clasificar_cambio(commit: Commit, config: Configuracion) -> str:
    """Tipo de cambio de un commit. Un commit solo de docs o solo de infra toma ese tipo
    antes de evaluar palabras de correccion, para que 'fix typo' en documentacion no cuente
    como correccion de errores."""
    if commit.tipo_cambio is not None:
        if commit.tipo_cambio not in TIPOS_CAMBIO:
            raise ValueError(f"tipo de cambio desconocido: {commit.tipo_cambio}")
        return commit.tipo_cambio
    categorias = {categoria_ruta(a, config) for a in commit.archivos}
    if categorias == {"documentacion"}:
        return "documentacion"
    if categorias == {"infraestructura"}:
        return "infraestructura"
    if _tiene_palabra(commit.mensaje, config.palabras.get("correccion", ())):
        return "correccion"
    if _tiene_palabra(commit.mensaje, config.palabras.get("refactor", ())):
        return "refactor"
    if _tiene_palabra(commit.mensaje, config.palabras.get("funcionalidad", ())):
        return "funcionalidad"
    return "otro"


def calcular_senales(actividad: Actividad, config: Configuracion) -> Senales:
    conteo = dict.fromkeys((*CATEGORIAS_RUTA, "codigo"), 0)
    for commit in actividad.commits:
        for archivo in commit.archivos:
            conteo[categoria_ruta(archivo, config)] += 1
    total = sum(conteo.values())
    n = len(actividad.commits)
    correcciones = sum(1 for c in actividad.commits if clasificar_cambio(c, config) == "correccion")

    def frac(clave: str) -> float:
        return conteo[clave] / total if total else 0.0

    return Senales(
        n_commits=n,
        f_infraestructura=frac("infraestructura"),
        f_documentacion=frac("documentacion"),
        f_frontend=frac("frontend"),
        f_pruebas=frac("pruebas"),
        f_codigo=frac("codigo"),
        f_correccion=correcciones / n if n else 0.0,
        revisiones=actividad.revisiones,
        comentarios=actividad.comentarios,
        issues_atendidos=actividad.issues_atendidos,
        repos=len({c.repo for c in actividad.commits if c.repo}),
        categorias_activas=sum(1 for v in conteo.values() if total and v / total >= 0.10),
    )
