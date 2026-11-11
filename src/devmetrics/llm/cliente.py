"""Interfaz unica de chat sobre LangChain con Gemini (principal) y Ollama (respaldo)."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
from langchain_core import exceptions as lce
from langchain_core.language_models import BaseChatModel

from devmetrics.llm.errores import (
    ErrorAccesoDenegado,
    ErrorClaveInvalida,
    ErrorConfiguracion,
    ErrorCupoAgotado,
    ErrorLLM,
    ErrorProveedor,
    ErrorServidor,
    ErrorSinRed,
    ErrorTodosFallaron,
)

PROVEEDORES = ("gemini", "ollama")
MODELO_GEMINI = "gemini-3.5-flash-lite"
MODELO_OLLAMA = "qwen3:0.6b"
# Solo se reintenta lo transitorio; el resto (cupo, clave, solicitud invalida, respuesta vacia)
# pasa directo al respaldo. Un 429 se trata como cupo agotado sin distinguir el limite por
# minuto del diario: la conmutacion inmediata evita esperar y gastar mas cupo.
_REINTENTABLES = (ErrorSinRed, ErrorServidor)
_CLAVE_GOOGLE = re.compile(r"(?:AIza|AQ\.)[0-9A-Za-z_.\-]{20,}")
registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigLLM:
    proveedor: str = "gemini"
    respaldo: str | None = "ollama"
    temperature: float = 0.0
    max_tokens: int = 1024
    max_reintentos: int = 2
    espera_base: float = 1.0
    timeout: float = 60.0
    modelo_gemini: str = MODELO_GEMINI
    modelo_ollama: str = MODELO_OLLAMA

    def __post_init__(self):
        for p in (self.proveedor, self.respaldo):
            if p is not None and p not in PROVEEDORES:
                raise ErrorConfiguracion(
                    f"Proveedor desconocido: {p!r}. Opciones: {', '.join(PROVEEDORES)}."
                )
        if self.respaldo == self.proveedor:
            object.__setattr__(self, "respaldo", None)
        if self.max_reintentos < 0 or self.max_tokens <= 0 or self.timeout <= 0:
            raise ErrorConfiguracion("max_reintentos >= 0, max_tokens > 0 y timeout > 0.")
        if not 0 <= self.temperature <= 2:
            raise ErrorConfiguracion("temperature debe estar entre 0 y 2.")

    @classmethod
    def desde_entorno(cls, env=None) -> ConfigLLM:
        """Lee DEVMETRICS_LLM_PROVIDER, DEVMETRICS_LLM_FALLBACK ('none' lo desactiva),
        DEVMETRICS_GEMINI_MODEL, DEVMETRICS_OLLAMA_MODEL, DEVMETRICS_LLM_TEMPERATURE,
        DEVMETRICS_LLM_MAX_TOKENS y DEVMETRICS_LLM_MAX_RETRIES."""
        env = os.environ if env is None else env
        respaldo = (env.get("DEVMETRICS_LLM_FALLBACK") or "ollama").strip().lower()
        return cls(
            proveedor=(env.get("DEVMETRICS_LLM_PROVIDER") or "gemini").strip().lower(),
            respaldo=None if respaldo in ("", "none") else respaldo,
            modelo_gemini=env.get("DEVMETRICS_GEMINI_MODEL") or MODELO_GEMINI,
            modelo_ollama=env.get("DEVMETRICS_OLLAMA_MODEL") or MODELO_OLLAMA,
            **_numeros(env),
        )


def _numeros(env) -> dict:
    campos = {
        "temperature": ("DEVMETRICS_LLM_TEMPERATURE", float),
        "max_tokens": ("DEVMETRICS_LLM_MAX_TOKENS", int),
        "max_reintentos": ("DEVMETRICS_LLM_MAX_RETRIES", int),
    }
    resultado = {}
    for campo, (variable, tipo) in campos.items():
        valor = env.get(variable, "").strip()
        if valor:
            try:
                resultado[campo] = tipo(valor)
            except ValueError:
                raise ErrorConfiguracion(f"{variable} debe ser numerico, no {valor!r}.") from None
    return resultado


def construir_modelo(proveedor: str, config: ConfigLLM, env=None) -> BaseChatModel:
    """Crea el modelo de chat de LangChain. Los reintentos los gestiona ClienteLLM."""
    env = os.environ if env is None else env
    if proveedor == "gemini":
        clave = env.get("GOOGLE_API_KEY", "").strip()
        if not clave:
            raise ErrorConfiguracion(
                "Falta GOOGLE_API_KEY en .env. Obtenla en https://aistudio.google.com/apikey."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.modelo_gemini,
            google_api_key=clave,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_retries=0,
            timeout=config.timeout,
        )
    if proveedor == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.modelo_ollama,
            base_url=env.get("OLLAMA_HOST") or None,
            temperature=config.temperature,
            num_predict=config.max_tokens,
            client_kwargs={"timeout": config.timeout},
        )
    raise ErrorConfiguracion(f"Proveedor desconocido: {proveedor!r}.")


def _codigo(exc: BaseException) -> int | None:
    for atributo in ("status_code", "code"):
        valor = getattr(exc, atributo, None)
        if isinstance(valor, int):
            return valor
    return None


def clasificar_error(exc: BaseException, proveedor: str) -> ErrorLLM:
    """Traduce una excepcion de LangChain o del SDK a un error propio con mensaje claro."""
    if isinstance(exc, ErrorLLM):
        return exc
    texto = str(exc)
    minusculas = texto.lower()
    codigo = _codigo(exc)
    if (
        isinstance(exc, lce.ModelRateLimitError)
        or codigo == 429
        or "resource_exhausted" in minusculas
    ):
        return ErrorCupoAgotado(
            f"{proveedor}: cupo o limite de solicitudes agotado. Espera o cambia al respaldo."
        )
    clave_mala = "api key" in minusculas and ("invalid" in minusculas or "not valid" in minusculas)
    if isinstance(exc, lce.ModelAuthenticationError) or codigo == 401 or clave_mala:
        if proveedor == "gemini":
            return ErrorClaveInvalida("gemini: clave rechazada. Revisa GOOGLE_API_KEY en .env.")
        return ErrorClaveInvalida(f"{proveedor}: acceso denegado ({codigo or 'autenticacion'}).")
    if isinstance(exc, lce.ModelPermissionDeniedError) or codigo == 403:
        detalle = _CLAVE_GOOGLE.sub("[clave]", texto)
        return ErrorAccesoDenegado(f"{proveedor}: acceso denegado (403): {detalle[:250]}")
    sin_red = (
        lce.ModelConnectionError,
        lce.ModelTimeoutError,
        httpx.TransportError,
        ConnectionError,
        TimeoutError,
    )
    if isinstance(exc, sin_red):
        if proveedor == "ollama":
            detalle = "Ollama no responde; verifica que este en ejecucion"
        else:
            detalle = "sin conexion con el servicio; revisa la red"
        return ErrorSinRed(f"{proveedor}: {detalle}.")
    detalle = _CLAVE_GOOGLE.sub("[clave]", texto)[:200]
    if (codigo is not None and codigo >= 500) or "unavailable" in minusculas:
        return ErrorServidor(f"{proveedor}: servicio no disponible: {detalle}")
    return ErrorProveedor(f"{proveedor}: {type(exc).__name__}: {detalle}")


class ClienteLLM:
    """Invoca el proveedor principal con reintentos y conmuta al respaldo si falla."""

    def __init__(
        self,
        config: ConfigLLM | None = None,
        *,
        modelos: dict[str, BaseChatModel] | None = None,
        env=None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self.config = config or ConfigLLM.desde_entorno(env)
        self._modelos = dict(modelos or {})
        self._env = env
        self._dormir = dormir
        self.ultimo_proveedor: str | None = None

    def _modelo(self, proveedor: str) -> BaseChatModel:
        if proveedor not in self._modelos:
            self._modelos[proveedor] = construir_modelo(proveedor, self.config, self._env)
        return self._modelos[proveedor]

    def _con_reintentos(self, proveedor: str, mensajes) -> str:
        intento = 0
        while True:
            try:
                texto = str(self._modelo(proveedor).invoke(mensajes).text).strip()
            except Exception as exc:  # noqa: BLE001 - se clasifica y se relanza tipado
                error = clasificar_error(exc, proveedor)
                if not isinstance(error, _REINTENTABLES) or intento >= self.config.max_reintentos:
                    raise error from exc
                self._dormir(self.config.espera_base * 2**intento)
                intento += 1
            else:
                if not texto:
                    raise ErrorProveedor(
                        f"{proveedor}: respuesta vacia (max_tokens demasiado bajo?)."
                    )
                return texto

    def invocar(self, mensajes) -> str:
        """`mensajes` admite texto o la lista de mensajes de LangChain. Devuelve el texto."""
        errores: list[ErrorLLM] = []
        self.ultimo_proveedor = None
        orden = [self.config.proveedor] + ([self.config.respaldo] if self.config.respaldo else [])
        for proveedor in orden:
            try:
                texto = self._con_reintentos(proveedor, mensajes)
            except ErrorLLM as error:
                errores.append(error)
                registro.warning("Proveedor %s fallo: %s", proveedor, error)
                continue
            self.ultimo_proveedor = proveedor
            return texto
        if len(errores) == 1:
            raise errores[0]
        raise ErrorTodosFallaron(errores)

    def flujo(self, mensajes) -> Iterator[str]:
        """Emite la respuesta por fragmentos de texto (`.stream()` del modelo de LangChain).

        Conmuta al respaldo solo si el proveedor falla antes de emitir el primer fragmento; un
        corte a mitad de la respuesta se propaga porque ya se mostro texto parcial. No reintenta
        errores transitorios (a diferencia de `invocar`).
        """
        errores: list[ErrorLLM] = []
        self.ultimo_proveedor = None
        orden = [self.config.proveedor] + ([self.config.respaldo] if self.config.respaldo else [])
        for proveedor in orden:
            emitido = False
            try:
                for trozo in self._modelo(proveedor).stream(mensajes):
                    texto = str(trozo.text)
                    if texto:
                        emitido = True
                        yield texto
                if not emitido:
                    raise ErrorProveedor(
                        f"{proveedor}: respuesta vacia (max_tokens demasiado bajo?)."
                    )
            except Exception as exc:  # noqa: BLE001 - se clasifica y se relanza tipado
                error = exc if isinstance(exc, ErrorLLM) else clasificar_error(exc, proveedor)
                if emitido:
                    raise error from exc
                errores.append(error)
                registro.warning("Proveedor %s fallo: %s", proveedor, error)
                continue
            self.ultimo_proveedor = proveedor
            return
        if len(errores) == 1:
            raise errores[0]
        raise ErrorTodosFallaron(errores)
