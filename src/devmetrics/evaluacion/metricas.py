"""Metricas de recuperacion (deterministas) y de generacion (LLM como juez, con cache).

Recuperacion: una fuente se identifica con `clave_de_fuente` (id de documento interno o
`dev:<login>`), de modo que las metricas se calculan contra `fuentes_esperadas` sin LLM.
Generacion: faithfulness (afirmaciones respaldadas por el contexto) y answer relevancy
(similitud entre la pregunta y preguntas que el juez deduce de la respuesta), segun las
definiciones de RAGAS; aqui se calculan con el cliente del proyecto, sin dependencia nueva.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from devmetrics.recuperacion import Fragmento

PREGUNTAS_RELEVANCIA = 3

PROMPT_FIDELIDAD = """Eres un verificador estricto. Descompón la RESPUESTA en afirmaciones \
atómicas sobre hechos (ignora saludos, la lista de fuentes y las frases de cortesía) y decide \
para cada una si se puede inferir únicamente del CONTEXTO.

Devuelve solo JSON, sin texto adicional, con esta forma exacta:
{{"afirmaciones": [{{"texto": "...", "respaldada": true}}]}}

<CONTEXTO>
{contexto}
</CONTEXTO>

<RESPUESTA>
{respuesta}
</RESPUESTA>"""

PROMPT_RELEVANCIA = """Dada la RESPUESTA de un asistente, escribe {n} preguntas distintas que \
esa respuesta contesta directamente. Devuelve solo JSON, sin texto adicional:
{{"preguntas": ["...", "..."]}}

<RESPUESTA>
{respuesta}
</RESPUESTA>"""

_PERFILES = ("druid", "bard", "cleric")


class _LLM(Protocol):
    def invocar(self, mensajes: list[dict]) -> str: ...


class _Embeddings(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


def clave_de_fuente(fragmento: Fragmento) -> str:
    """Identificador comparable con `fuentes_esperadas`: documento interno o `dev:<login>`."""
    meta = fragmento.metadatos
    if meta.get("documento"):
        return str(meta["documento"])
    return f"dev:{str(meta.get('desarrollador', '?')).casefold()}"


def _relevantes(fragmentos: Sequence[Fragmento], esperadas: Sequence[str]) -> list[bool]:
    objetivo = {e.casefold() for e in esperadas}
    return [clave_de_fuente(f).casefold() in objetivo for f in fragmentos]


def context_precision(fragmentos: Sequence[Fragmento], esperadas: Sequence[str]) -> float | None:
    """Precision media en los rangos relevantes (premia que lo relevante vaya primero).

    None si no hay fuentes esperadas (el caso no tiene referencia). 0.0 si se recupera algo
    pero nada relevante, o si no se recupera nada.
    """
    if not esperadas:
        return None
    # Varios chunks de una misma fuente cuentan una vez: citar dos veces no mejora la precision.
    vistas: set[str] = set()
    unicos = []
    for f in fragmentos:
        if clave_de_fuente(f) not in vistas:
            vistas.add(clave_de_fuente(f))
            unicos.append(f)
    aciertos = 0
    suma = 0.0
    for rango, relevante in enumerate(_relevantes(unicos, esperadas), 1):
        if relevante:
            aciertos += 1
            suma += aciertos / rango
    return suma / aciertos if aciertos else 0.0


def context_recall(fragmentos: Sequence[Fragmento], esperadas: Sequence[str]) -> float | None:
    """Fraccion de las fuentes esperadas que aparecen entre los fragmentos recuperados."""
    if not esperadas:
        return None
    halladas = {clave_de_fuente(f).casefold() for f in fragmentos}
    objetivo = {e.casefold() for e in esperadas}
    return len(objetivo & halladas) / len(objetivo)


def extraer_json(texto: str) -> dict | None:
    """Primer objeto JSON de la salida del juez (tolera cercos de codigo y texto alrededor)."""
    limpio = re.sub(r"```(?:json)?", "", texto or "")
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        dato = json.loads(limpio[inicio : fin + 1])
    except json.JSONDecodeError:
        return None
    return dato if isinstance(dato, dict) else None


def faithfulness(llm: _LLM, contexto: str, respuesta: str) -> float | None:
    """Fraccion de afirmaciones de la respuesta que el juez considera respaldadas por el contexto.

    None si el juez no devuelve JSON valido o no hay afirmaciones (no se reintenta).
    """
    pedido = PROMPT_FIDELIDAD.format(contexto=contexto, respuesta=respuesta)
    dato = extraer_json(llm.invocar([{"role": "user", "content": pedido}]))
    lista = dato.get("afirmaciones") if dato else None
    if not isinstance(lista, list):
        return None
    valores = [a.get("respaldada") is True for a in lista if isinstance(a, dict)]
    return sum(valores) / len(valores) if valores else None


def similitud_coseno(a: Sequence[float], b: Sequence[float]) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    norma = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return producto / norma if norma else 0.0


def answer_relevancy(
    llm: _LLM, embeddings: _Embeddings, pregunta: str, respuesta: str
) -> float | None:
    """Similitud coseno media entre la pregunta y las que el juez deduce de la respuesta."""
    pedido = PROMPT_RELEVANCIA.format(n=PREGUNTAS_RELEVANCIA, respuesta=respuesta)
    dato = extraer_json(llm.invocar([{"role": "user", "content": pedido}]))
    lista = dato.get("preguntas") if dato else None
    if not isinstance(lista, list):
        return None
    generadas = [p for p in lista if isinstance(p, str) and p.strip()]
    if not generadas:
        return None
    base = embeddings.embed_query(pregunta)
    puntajes = [similitud_coseno(base, embeddings.embed_query(p)) for p in generadas]
    return sum(puntajes) / len(puntajes)


def es_abstencion(texto: str) -> bool:
    """La respuesta declara evidencia insuficiente o confianza baja (lo esperado si hay poco)."""
    t = " ".join((texto or "").lower().replace("*", "").split())
    return any(
        f in t
        for f in (
            "evidencia insuficiente",
            "datos insuficientes",
            "confianza baja",
            "baja confianza",
            "confianza: baja",
        )
    )


def coincide_perfil(texto: str, perfil: str | None) -> bool | None:
    """True si la respuesta cumple el perfil esperado.

    `insuficiente` equivale a abstenerse; `mixto` acepta decir "mixto" o abstenerse; una clase
    se cumple si la respuesta nombra primero esa clase que cualquier otra (heuristica de
    texto: no distingue una negacion). None si el caso no define perfil.
    """
    if not perfil:
        return None
    t = (texto or "").lower()
    if perfil == "insuficiente":
        return es_abstencion(texto)
    if perfil == "mixto":
        return "mixto" in t or es_abstencion(texto)
    pos = t.find(perfil)
    if pos < 0:
        return False
    otros = [t.find(o) for o in _PERFILES if o != perfil]
    return all(p < 0 or p > pos for p in otros)


class CacheLLM:
    """Respuestas del LLM guardadas en JSON por huella de (modelo, mensajes)."""

    def __init__(self, ruta: str | Path | None):
        self.ruta = Path(ruta) if ruta else None
        self._datos: dict[str, str] = {}
        if self.ruta and self.ruta.exists():
            try:
                self._datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._datos = {}

    @staticmethod
    def clave(modelo: str, mensajes: list[dict]) -> str:
        base = json.dumps([modelo, mensajes], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def obtener(self, clave: str) -> str | None:
        return self._datos.get(clave)

    def guardar(self, clave: str, texto: str) -> None:
        self._datos[clave] = texto
        if self.ruta:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal = self.ruta.with_suffix(".tmp")
            temporal.write_text(json.dumps(self._datos, ensure_ascii=False), encoding="utf-8")
            temporal.replace(self.ruta)  # atomico: una interrupcion no deja la cache a medias

    def __len__(self) -> int:
        return len(self._datos)


class LLMConCache:
    """Envuelve un LLM: una respuesta ya vista no vuelve a pedirse.

    `pausa` espacia las llamadas reales (limites por minuto de la capa gratuita). Un error del
    LLM se propaga sin reintentos para que el llamador pare y reporte.
    """

    def __init__(
        self,
        llm: _LLM,
        cache: CacheLLM,
        modelo: str,
        *,
        pausa: float = 0.0,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._llm = llm
        self._cache = cache
        self._modelo = modelo
        self._pausa = pausa
        self._dormir = dormir
        self.llamadas_reales = 0
        self.aciertos_de_cache = 0

    def invocar(self, mensajes: list[dict]) -> str:
        clave = self._cache.clave(self._modelo, mensajes)
        previo = self._cache.obtener(clave)
        if previo is not None:
            self.aciertos_de_cache += 1
            return previo
        if self._pausa and self.llamadas_reales:
            self._dormir(self._pausa)
        texto = self._llm.invocar(mensajes)
        self.llamadas_reales += 1
        self._cache.guardar(clave, texto)
        return texto
