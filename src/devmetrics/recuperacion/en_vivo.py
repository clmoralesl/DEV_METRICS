"""Consulta de GitHub en vivo para desarrolladores que no estan en el indice.

Descarga la actividad con la ingesta del issue 7 (usa la cache local si existe), la documenta
y segmenta como los perfiles indexados y la consulta en un indice efimero en memoria.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

from langchain_core.embeddings import Embeddings
from langchain_core.tools import StructuredTool

from devmetrics.indexacion import IndiceVectorial
from devmetrics.ingesta import CacheLocal, ClienteGitHub, Limites, ingerir
from devmetrics.perfiles import documentos_de, segmentar

from .fragmentos import ORIGEN_EN_VIVO, Fragmento, Recuperacion, resumir

LIMITES_EN_VIVO = Limites(max_commits=100, max_prs=50, max_issues=50, max_comentarios=0)


def consultar_en_vivo(
    consulta: str,
    desarrollador: str,
    repositorios: Iterable[str],
    cliente: ClienteGitHub,
    embeddings: Embeddings,
    *,
    cache: CacheLocal | None = None,
    limites: Limites = LIMITES_EN_VIVO,
    k: int = 4,
    repositorio: str | None = None,
    tipo_fuente: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> Recuperacion:
    """Actividad de `desarrollador` en `repositorios`, recuperada por similitud con `consulta`.

    Un repositorio que falla (red, 404, limite de tasa) no impide usar los demas: se reporta en
    `avisos`. Los filtros `repositorio`, `tipo_fuente`, `desde` y `hasta` se aplican igual que en el
    indice persistente. Si ninguno responde o el desarrollador no tiene actividad, `sin_resultados`.
    """
    repos = list(repositorios)
    if not repos:
        return Recuperacion(avisos=["no se indicaron repositorios para la consulta en vivo"])
    resultado = ingerir(repos, cliente, cache or CacheLocal(), limites=limites)
    avisos = [f"GitHub en vivo, {repo}: {error}" for repo, error in resultado.errores.items()]
    avisos += [f"GitHub en vivo, {r}: no consultado (limite de tasa)" for r in resultado.pendientes]
    docs = documentos_de(desarrollador, resultado.datos.values())
    if not docs:
        if resultado.datos:
            avisos.append(f"{desarrollador} no tiene actividad en los repositorios consultados")
        return Recuperacion(avisos=avisos)
    indice = IndiceVectorial(embeddings, ruta=None, coleccion=f"vivo_{uuid.uuid4().hex}")
    indice.indexar(segmentar(docs))
    encontrados = indice.consultar(
        consulta, k=k, repositorio=repositorio, tipo_fuente=tipo_fuente, desde=desde, hasta=hasta
    )
    return Recuperacion([Fragmento.desde(r, ORIGEN_EN_VIVO) for r in encontrados], avisos)


def crear_en_vivo(
    repositorios: Iterable[str],
    cliente: ClienteGitHub,
    embeddings: Embeddings,
    *,
    cache: CacheLocal | None = None,
    limites: Limites = LIMITES_EN_VIVO,
) -> Callable[..., Recuperacion]:
    """Adaptador para `RecuperadorCombinado(en_vivo=...)`: fija repositorios, cliente y cache.

    `embeddings` debe ser el mismo modelo con que se indexaron las colecciones, o las distancias
    de ambas fuentes no serian comparables.
    """
    repos = list(repositorios)

    def en_vivo(consulta: str, desarrollador: str, k: int, **filtros) -> Recuperacion:
        return consultar_en_vivo(
            consulta, desarrollador, repos, cliente, embeddings,
            cache=cache, limites=limites, k=k, **filtros,
        )  # fmt: skip

    return en_vivo


def crear_herramienta_github(
    cliente: ClienteGitHub,
    embeddings: Embeddings,
    *,
    cache: CacheLocal | None = None,
    limites: Limites = LIMITES_EN_VIVO,
    k: int = 4,
) -> StructuredTool:
    """Herramienta del agente: consulta GitHub en vivo si el desarrollador no esta indexado."""

    def consultar_github(consulta: str, desarrollador: str, repositorios: list[str]) -> str:
        try:
            rec = consultar_en_vivo(
                consulta,
                desarrollador,
                repositorios,
                cliente,
                embeddings,
                cache=cache,
                limites=limites,
                k=k,
            )
        except Exception as exc:  # la herramienta no debe romper el ciclo del agente
            motivo = f"{type(exc).__name__}: {resumir(exc)}"
            return f"SIN RESULTADOS (fallo de la consulta en vivo: {motivo})."
        return rec.formatear()

    return StructuredTool.from_function(
        consultar_github,
        name="consultar_github",
        description=(
            "Consulta la API de GitHub en vivo y devuelve la actividad relevante de un "
            "desarrollador (commits, pull requests, revisiones, issues) con su fuente. Usar solo "
            "cuando se necesita actividad reciente que el indice no contiene. Argumentos: "
            "consulta (que se busca), "
            "desarrollador (login) y repositorios (lista 'propietario/repo')."
        ),
    )
