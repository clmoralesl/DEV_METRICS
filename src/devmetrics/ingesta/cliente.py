from __future__ import annotations

import time
from collections.abc import Callable, Iterator

import requests

from .errores import (
    ErrorAccesoDenegado,
    ErrorAutenticacion,
    ErrorLimiteTasa,
    ErrorNoEncontrado,
    ErrorRed,
    ErrorRepositorioVacio,
    ErrorServidor,
)

URL_BASE = "https://api.github.com"


class ClienteGitHub:
    """Cliente minimo de la API REST de GitHub con paginacion y manejo de limite de tasa."""

    def __init__(
        self,
        token: str | None = None,
        *,
        session=None,
        base_url: str = URL_BASE,
        max_reintentos: int = 3,
        max_espera: float = 60.0,
        timeout: float = 30.0,
        dormir: Callable[[float], None] = time.sleep,
        ahora: Callable[[], float] = time.time,
    ):
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._max_reintentos = max_reintentos
        self._max_espera = max_espera
        self._timeout = timeout
        self._dormir = dormir
        self._ahora = ahora
        self._cabeceras = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "devmetrics",
        }
        if token:
            self._cabeceras["Authorization"] = f"Bearer {token}"
        self.llamadas = 0

    def _espera_limite(self, resp) -> float | None:
        """Segundos hasta reponer el cupo si la respuesta es de limite de tasa; None si no."""
        h = resp.headers
        if h.get("Retry-After") is not None:
            try:
                return float(h["Retry-After"])
            except ValueError:
                return 60.0
        if h.get("X-RateLimit-Remaining") == "0":
            reset = float(h.get("X-RateLimit-Reset", 0))
            return max(reset - self._ahora(), 0.0) + 1.0
        if resp.status_code in (403, 429) and "rate limit" in (resp.text or "").lower():
            return 60.0
        return None

    def _solicitar(self, url: str, params: dict | None):
        intentos = 0
        while True:
            intentos += 1
            ultimo = intentos > self._max_reintentos
            try:
                self.llamadas += 1
                resp = self._session.get(
                    url, params=params, headers=self._cabeceras, timeout=self._timeout
                )
            except requests.RequestException as exc:
                if ultimo:
                    raise ErrorRed(f"sin respuesta de GitHub: {exc}") from exc
                self._dormir(2.0 ** (intentos - 1))
                continue

            codigo = resp.status_code
            if codigo == 200:
                return resp
            if codigo == 404:
                raise ErrorNoEncontrado(f"recurso no encontrado: {url}")
            if codigo == 409:
                raise ErrorRepositorioVacio(f"repositorio vacio: {url}")
            if codigo == 401:
                raise ErrorAutenticacion("GITHUB_TOKEN rechazado por GitHub (401)")
            if codigo in (403, 429):
                espera = self._espera_limite(resp)
                if espera is None:
                    raise ErrorAccesoDenegado(f"acceso denegado ({codigo}): {url}")
                if espera > self._max_espera or ultimo:
                    raise ErrorLimiteTasa(espera)
                self._dormir(espera)
                continue
            if codigo >= 500:
                if ultimo:
                    raise ErrorServidor(f"GitHub respondio {codigo}: {url}")
                self._dormir(2.0 ** (intentos - 1))
                continue
            raise ErrorAccesoDenegado(f"respuesta inesperada {codigo}: {url}")

    def obtener(self, ruta: str, params: dict | None = None):
        return self._solicitar(f"{self._base}{ruta}", params).json()

    def paginar(
        self, ruta: str, params: dict | None = None, max_items: int | None = None
    ) -> Iterator[dict]:
        """Itera los elementos de un listado, siguiendo la cabecera Link hasta max_items."""
        url, parametros = f"{self._base}{ruta}", {"per_page": 100, **(params or {})}
        entregados = 0
        while url:
            resp = self._solicitar(url, parametros)
            for item in resp.json():
                if max_items is not None and entregados >= max_items:
                    return
                entregados += 1
                yield item
            if max_items is not None and entregados >= max_items:
                return
            url, parametros = (resp.links or {}).get("next", {}).get("url"), None
