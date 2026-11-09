"""Validacion de las salidas estructuradas de los prompts (CA6)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

TIPOS_CAMBIO = (
    "correccion",
    "funcionalidad",
    "documentacion",
    "infraestructura",
    "refactor",
    "otro",
)
CLASES = ("Druid", "Cleric", "Bard")
CONFIANZAS = ("alta", "media", "baja", "datos_insuficientes")
# Replica el margen de configuracion del modelo de arquetipos (issue 4).
MARGEN_MINIMO = 0.20
TOLERANCIA_SUMA = 0.01

_PENSAMIENTO = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_CERCA = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class ErrorSalida(ValueError):
    """La respuesta del modelo no es JSON o no cumple el esquema del prompt."""

    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


def extraer_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta, tolerando cercas y bloques <think>."""
    limpio = _PENSAMIENTO.sub("", texto or "")
    for candidato in [*_CERCA.findall(limpio), limpio]:
        objeto = _primer_objeto(candidato)
        if objeto is not None:
            return objeto
    raise ErrorSalida(["la respuesta no contiene un objeto JSON valido"])


def _primer_objeto(texto: str) -> dict | None:
    decodificador = json.JSONDecoder()
    inicio = texto.find("{")
    while inicio != -1:
        try:
            objeto, _ = decodificador.raw_decode(texto[inicio:])
        except json.JSONDecodeError:
            inicio = texto.find("{", inicio + 1)
            continue
        if isinstance(objeto, dict):
            return objeto
        inicio = texto.find("{", inicio + 1)
    return None


def _texto(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _numero(valor: object) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _opcional_razonamiento(datos: dict, errores: list[str]) -> None:
    if "razonamiento" in datos and not _texto(datos["razonamiento"]):
        errores.append("razonamiento, si aparece, debe ser texto no vacio")


def validar_tipo_cambio(datos: dict) -> dict:
    errores: list[str] = []
    if datos.get("tipo") not in TIPOS_CAMBIO:
        errores.append(f"tipo invalido: {datos.get('tipo')!r}; validos: {TIPOS_CAMBIO}")
    if not _texto(datos.get("justificacion")):
        errores.append("justificacion ausente o vacia")
    _opcional_razonamiento(datos, errores)
    if errores:
        raise ErrorSalida(errores)
    return datos


def validar_arquetipo(
    datos: dict,
    margen_minimo: float = MARGEN_MINIMO,
    fuentes_disponibles: Iterable[str] | None = None,
) -> dict:
    errores: list[str] = []
    mezcla = datos.get("mezcla")
    puntajes: dict[str, float] = {}
    if not isinstance(mezcla, dict) or set(mezcla) != set(CLASES):
        errores.append(f"mezcla debe tener exactamente las claves {CLASES}")
    elif not all(_numero(v) and 0 <= v <= 1 for v in mezcla.values()):
        errores.append("los puntajes de la mezcla deben ser numeros entre 0 y 1")
    elif abs(sum(mezcla.values()) - 1) > TOLERANCIA_SUMA:
        errores.append(f"la mezcla suma {sum(mezcla.values()):.3f}, debe sumar 1")
    else:
        puntajes = dict(mezcla)

    confianza = datos.get("confianza")
    if confianza not in CONFIANZAS:
        errores.append(f"confianza invalida: {confianza!r}; validas: {CONFIANZAS}")

    dominante = datos.get("dominante")
    if dominante not in (*CLASES, "mixto"):
        errores.append(f"dominante invalido: {dominante!r}")
    elif confianza in ("baja", "datos_insuficientes") and dominante != "mixto":
        errores.append("con confianza baja o datos_insuficientes el dominante debe ser mixto")
    elif dominante in CLASES and puntajes:
        ordenados = sorted(puntajes.values(), reverse=True)
        if puntajes[dominante] != ordenados[0]:
            errores.append("el dominante no es la clase con mayor puntaje")
        elif ordenados[0] - ordenados[1] < margen_minimo - 1e-9:
            errores.append(f"el dominante no supera a la segunda clase por {margen_minimo}")

    evidencias = datos.get("evidencias")
    permitidas = None if fuentes_disponibles is None else set(fuentes_disponibles)
    if not isinstance(evidencias, list) or not evidencias:
        errores.append("evidencias debe ser una lista no vacia")
    else:
        for i, evidencia in enumerate(evidencias):
            if not (
                isinstance(evidencia, dict)
                and _texto(evidencia.get("fuente"))
                and _texto(evidencia.get("descripcion"))
            ):
                errores.append(f"evidencias[{i}] requiere fuente y descripcion")
            elif permitidas is not None and evidencia["fuente"] not in permitidas:
                errores.append(f"evidencias[{i}] cita una fuente que no esta en el contexto")

    if confianza in ("baja", "datos_insuficientes") and not _texto(datos.get("faltante")):
        errores.append("con confianza baja o datos_insuficientes se requiere faltante")
    _opcional_razonamiento(datos, errores)
    if errores:
        raise ErrorSalida(errores)
    return datos


def validar_recomendacion(
    datos: dict,
    fuentes_disponibles: Iterable[str],
    aliases_disponibles: Iterable[str] | None = None,
) -> dict:
    errores: list[str] = []
    suficiente = datos.get("evidencia_suficiente")
    if not isinstance(suficiente, bool):
        errores.append("evidencia_suficiente debe ser booleano")
    if not _texto(datos.get("respuesta")):
        errores.append("respuesta ausente o vacia")
    candidatos = datos.get("candidatos")
    fuentes = datos.get("fuentes")
    if not isinstance(candidatos, list):
        errores.append("candidatos debe ser una lista")
        candidatos = []
    if not isinstance(fuentes, list) or not all(_texto(f) for f in fuentes):
        errores.append("fuentes debe ser una lista de identificadores")
        fuentes = []

    if suficiente is False:
        if candidatos:
            errores.append("sin evidencia suficiente no debe haber candidatos")
        if not _texto(datos.get("faltante")):
            errores.append("sin evidencia suficiente se requiere faltante")
    elif suficiente is True:
        if not candidatos:
            errores.append("con evidencia suficiente se requiere al menos un candidato")
        if not fuentes:
            errores.append("con evidencia suficiente se requiere al menos una fuente")
        for i, candidato in enumerate(candidatos):
            citadas = candidato.get("fuentes") if isinstance(candidato, dict) else None
            if not (
                isinstance(candidato, dict)
                and _texto(candidato.get("alias"))
                and _texto(candidato.get("justificacion"))
                and isinstance(citadas, list)
                and citadas
                and all(_texto(c) for c in citadas)
            ):
                errores.append(f"candidatos[{i}] requiere alias, justificacion y fuentes")
            elif not set(citadas) <= set(fuentes):
                errores.append(f"candidatos[{i}] cita fuentes ausentes de la lista fuentes")

    todas = set(fuentes) | {
        f
        for c in candidatos
        if isinstance(c, dict) and isinstance(c.get("fuentes"), list)
        for f in c["fuentes"]
        if _texto(f)
    }
    inventadas = todas - set(fuentes_disponibles)
    if inventadas:
        errores.append(f"fuentes que no estan en el contexto: {sorted(inventadas)}")
    if aliases_disponibles is not None:
        desconocidos = {
            c["alias"] for c in candidatos if isinstance(c, dict) and _texto(c.get("alias"))
        } - set(aliases_disponibles)
        if desconocidos:
            errores.append(f"candidatos que no estan en el contexto: {sorted(desconocidos)}")
    _opcional_razonamiento(datos, errores)
    if errores:
        raise ErrorSalida(errores)
    return datos


VALIDADORES: dict[str, Callable[..., dict]] = {
    "tipo_cambio": validar_tipo_cambio,
    "clasificacion_arquetipo": validar_arquetipo,
    "recomendacion": validar_recomendacion,
}


def validar_salida(nombre: str, texto: str, **opciones: object) -> dict:
    """Extrae el JSON de `texto` y lo valida con el validador del prompt `nombre`."""
    if nombre not in VALIDADORES:
        raise ValueError(f"el prompt {nombre!r} no tiene salida estructurada")
    if nombre == "recomendacion" and "fuentes_disponibles" not in opciones:
        raise ValueError("recomendacion exige fuentes_disponibles para contrastar las citas")
    return VALIDADORES[nombre](extraer_json(texto), **opciones)
