"""Recuperador que combina la fuente interna y la externa (perfiles indexados, o GitHub en vivo)."""

from __future__ import annotations

from collections.abc import Callable

from devmetrics.indexacion import IndiceVectorial

from .fragmentos import ORIGEN_INDEXADO, ORIGEN_INTERNO, Fragmento, Recuperacion, resumir


class RecuperadorCombinado:
    """Consulta ambas fuentes, mezcla por distancia y cita el origen de cada fragmento.

    Los filtros de metadatos (desarrollador, repositorio, tipo de fuente, fechas) se aplican a la
    fuente externa; `categoria` a la interna. Cada fuente es independiente: si una falla, la otra
    responde y el fallo queda en `avisos`. Si se da `en_vivo` y se pide un desarrollador que no
    esta en el indice (ningun fragmento suyo, con o sin filtros), se consulta GitHub en vivo con
    `en_vivo(consulta, desarrollador, k, repositorio=, tipo_fuente=, desde=, hasta=)`; ver
    `crear_en_vivo`. Las distancias de ambas fuentes solo son comparables si los indices y el
    adaptador en vivo usan el mismo modelo de embeddings: el llamador debe garantizarlo.
    """

    def __init__(
        self,
        conocimiento: IndiceVectorial,
        perfiles: IndiceVectorial,
        *,
        en_vivo: Callable[..., Recuperacion] | None = None,
        k_interna: int = 2,
        k_externa: int = 4,
    ):
        self._conocimiento = conocimiento
        self._perfiles = perfiles
        self._en_vivo = en_vivo
        self.k_interna = k_interna
        self.k_externa = k_externa

    def recuperar(
        self,
        consulta: str,
        *,
        k: int | None = None,
        k_interna: int | None = None,
        k_externa: int | None = None,
        categoria: str | None = None,
        desarrollador: str | None = None,
        repositorio: str | None = None,
        tipo_fuente: str | None = None,
        desde: str | None = None,
        hasta: str | None = None,
        distancia_maxima: float | None = None,
    ) -> Recuperacion:
        """`k` limita el total tras mezclar; `k_interna` y `k_externa` limitan cada fuente."""
        k_int = self.k_interna if k_interna is None else k_interna
        k_ext = self.k_externa if k_externa is None else k_externa
        if k is not None and k <= 0:
            raise ValueError("k debe ser positivo")
        fragmentos: list[Fragmento] = []
        avisos: list[str] = []

        # La fuente interna no se filtra por desarrollador ni fechas: son criterios de actividad.
        if k_int > 0:
            try:
                filtros = {"categoria": categoria} if categoria else None
                fragmentos += [
                    Fragmento.desde(r, ORIGEN_INTERNO)
                    for r in self._conocimiento.consultar(consulta, k=k_int, filtros=filtros)
                ]
            except Exception as exc:
                avisos.append(f"fuente interna no disponible: {type(exc).__name__}: {resumir(exc)}")

        if k_ext > 0:
            try:
                externos = self._perfiles.consultar(
                    consulta,
                    k=k_ext,
                    desarrollador=desarrollador,
                    repositorio=repositorio,
                    tipo_fuente=tipo_fuente,
                    desde=desde,
                    hasta=hasta,
                )
                fragmentos += [Fragmento.desde(r, ORIGEN_INDEXADO) for r in externos]
                no_indexado = (
                    not externos
                    and desarrollador
                    and self._en_vivo is not None
                    and not self._perfiles.consultar(consulta, k=1, desarrollador=desarrollador)
                )
            except ValueError:
                raise  # filtros mal formados (fecha invalida): error del llamador, no de la fuente
            except Exception as exc:
                avisos.append(f"fuente externa no disponible: {type(exc).__name__}: {resumir(exc)}")
                no_indexado = False
            if no_indexado:
                try:
                    vivo = self._en_vivo(
                        consulta,
                        desarrollador,
                        k_ext,
                        repositorio=repositorio,
                        tipo_fuente=tipo_fuente,
                        desde=desde,
                        hasta=hasta,
                    )
                    fragmentos += vivo.fragmentos
                    avisos += vivo.avisos
                except Exception as exc:
                    avisos.append(
                        f"GitHub en vivo no disponible: {type(exc).__name__}: {resumir(exc)}"
                    )

        if distancia_maxima is not None:
            fragmentos = [f for f in fragmentos if f.distancia <= distancia_maxima]
        fragmentos.sort(key=lambda f: f.distancia)
        if k is not None:
            fragmentos = fragmentos[:k]
        return Recuperacion(fragmentos, avisos)
