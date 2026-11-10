from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from devmetrics.prompts import cargar
from devmetrics.recuperacion import Recuperacion

from .memoria import MemoriaVentana

PALABRAS_SEGUIMIENTO = 8


def _declara_insuficiente(texto: str) -> bool:
    """Detecta la frase en las primeras lineas, tolerando markdown, comillas y saludos."""
    inicio = " ".join(texto.splitlines()[:2]).lower().replace("*", "").replace("_", "")
    return "evidencia insuficiente" in inicio[:120]


class _Recuperador(Protocol):
    def recuperar(self, consulta: str, **filtros) -> Recuperacion: ...


class _LLM(Protocol):
    def invocar(self, mensajes: list[dict]) -> str: ...


@dataclass(frozen=True)
class Respuesta:
    texto: str
    evidencia_suficiente: bool
    fuentes: list[str] = field(default_factory=list)
    recuperacion: Recuperacion | None = None


def _insuficiente(motivo: str) -> str:
    return f"Evidencia insuficiente: {motivo}"


class Conversacion:
    """Cadena RAG con memoria: recupera, aumenta el prompt `sistema` y responde con citas.

    `Respuesta.fuentes` son las fuentes recuperadas que el texto cita literalmente.
    Sin fragmentos recuperados no se llama al LLM: la respuesta de evidencia insuficiente es
    determinista y no puede inventar datos. La ambiguedad la resuelve el prompt (pide precisar).
    """

    def __init__(
        self,
        recuperador: _Recuperador,
        llm: _LLM,
        *,
        ventana: int = 6,
        tecnica: str = "zero_shot",
        k: int | None = None,
    ):
        self._recuperador = recuperador
        self._llm = llm
        self._prompt = cargar("sistema")
        self._tecnica = tecnica
        self._k = k
        self.memoria = MemoriaVentana(ventana)
        self._ultima_busqueda: str | None = None

    def preguntar(self, consulta: str, **filtros) -> Respuesta:
        consulta = (consulta or "").strip()
        if not consulta:
            return self._cerrar(
                consulta, Respuesta("Indica qué quieres saber para poder ayudarte.", False)
            )
        if self._k is not None:
            filtros.setdefault("k", self._k)
        recuperacion = self._recuperador.recuperar(self._consulta_de_busqueda(consulta), **filtros)
        if recuperacion.sin_resultados:
            motivo = "; ".join(recuperacion.avisos) or "no hay fragmentos que respalden la consulta"
            texto = _insuficiente(
                f"{motivo}. Falta información sobre el desarrollador, repositorio o criterio "
                "consultado; indica un login o un requerimiento concreto."
            )
            return self._cerrar(consulta, Respuesta(texto, False, [], recuperacion))
        mensajes = self._prompt.mensajes(
            {
                "contexto": recuperacion.formatear(),
                "historial": self.memoria.formatear(),
                "consulta": consulta,
            },
            self._tecnica,
        )
        texto = self._llm.invocar(mensajes).strip()
        evidencia = not _declara_insuficiente(texto)
        fuentes = [c for c in recuperacion.fuentes if c in texto] if evidencia else []
        if evidencia:
            self._ultima_busqueda = consulta
        return self._cerrar(consulta, Respuesta(texto, evidencia, fuentes, recuperacion))

    def reiniciar(self) -> None:
        self.memoria.limpiar()
        self._ultima_busqueda = None

    def _consulta_de_busqueda(self, consulta: str) -> str:
        """Un seguimiento corto se busca junto a la ultima pregunta que si tuvo evidencia."""
        previa = self._ultima_busqueda
        if previa and len(consulta.split()) <= PALABRAS_SEGUIMIENTO:
            return f"{previa}\n{consulta}"
        return consulta

    def _cerrar(self, consulta: str, respuesta: Respuesta) -> Respuesta:
        # Un fallo del LLM propaga antes de llegar aqui y el turno no se registra.
        if consulta:
            self.memoria.agregar("usuario", consulta)
            self.memoria.agregar("asistente", respuesta.texto)
        return respuesta
