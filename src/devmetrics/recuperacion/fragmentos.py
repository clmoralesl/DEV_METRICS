"""Fragmentos recuperados con su cita de origen, y el resultado de una recuperacion."""

from __future__ import annotations

from dataclasses import dataclass, field

from devmetrics.indexacion import ResultadoConsulta

ORIGEN_INTERNO = "interna"
ORIGEN_INDEXADO = "externa_indexada"
ORIGEN_EN_VIVO = "externa_en_vivo"


def resumir(exc: Exception, largo: int = 120) -> str:
    """Mensaje de una excepcion acotado: las de red pueden traer URLs largas."""
    texto = " ".join(str(exc).split())
    return texto if len(texto) <= largo else texto[: largo - 3] + "..."


def citar(meta: dict, origen: str) -> str:
    """Cita legible y estable del origen de un chunk, a partir de sus metadatos."""
    pos = ""
    if meta.get("n_chunks"):
        pos = f", fragmento {int(meta.get('chunk', 0)) + 1}/{meta['n_chunks']}"
    if origen == ORIGEN_INTERNO:
        return (
            f"conocimiento interno: {meta.get('titulo', '?')} "
            f"({meta.get('origen', meta.get('documento', '?'))}{pos})"
        )
    rango = ""
    if meta.get("fecha_desde"):
        rango = f", {meta['fecha_desde']} a {meta.get('fecha_hasta') or meta['fecha_desde']}"
    en_vivo = " [consulta en vivo]" if origen == ORIGEN_EN_VIVO else ""
    return (
        f"GitHub: {meta.get('repositorio', '?')} / {meta.get('tipo_fuente', '?')} / "
        f"@{meta.get('desarrollador', '?')}{rango}{pos}{en_vivo}"
    )


@dataclass(frozen=True)
class Fragmento:
    texto: str
    cita: str
    origen: str
    distancia: float
    metadatos: dict = field(default_factory=dict)

    @classmethod
    def desde(cls, r: ResultadoConsulta, origen: str) -> Fragmento:
        return cls(r.texto, citar(r.metadatos, origen), origen, r.distancia, dict(r.metadatos))


@dataclass(frozen=True)
class Recuperacion:
    """Fragmentos ordenados por distancia, las fuentes citadas y los avisos de fuentes caidas.

    `sin_resultados` es True cuando ninguna fuente devolvio fragmentos; `avisos` explica si fue
    por ausencia de coincidencias o por fuentes que fallaron (no es lo mismo para el agente).
    """

    fragmentos: list[Fragmento] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def sin_resultados(self) -> bool:
        return not self.fragmentos

    @property
    def fuentes(self) -> list[str]:
        return list(dict.fromkeys(f.cita for f in self.fragmentos))

    def formatear(self) -> str:
        """Texto para el prompt o la salida de una herramienta: fragmentos numerados y fuentes."""
        if self.sin_resultados:
            motivo = "; ".join(self.avisos) or "sin coincidencias en las fuentes"
            return f"SIN RESULTADOS ({motivo})."
        lineas = [
            f"[{i}] {f.texto}\n    Fuente: {f.cita}" for i, f in enumerate(self.fragmentos, 1)
        ]
        if self.avisos:
            lineas.append("AVISOS: " + "; ".join(self.avisos))
        return "\n".join(lineas)
