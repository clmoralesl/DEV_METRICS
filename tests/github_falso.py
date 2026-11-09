"""Sesion HTTP falsa que sirve respuestas grabadas, con paginacion por cabecera Link."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

FIXTURES = Path(__file__).parent / "fixtures" / "github"
BASE = "https://api.github.com"


class RespuestaFalsa:
    def __init__(self, estado=200, cuerpo=None, cabeceras=None, links=None):
        self.status_code = estado
        self._cuerpo = cuerpo
        self.headers = cabeceras or {}
        self.links = links or {}
        self.text = json.dumps(cuerpo) if cuerpo is not None else ""

    def json(self):
        return self._cuerpo


class SesionFalsa:
    """rutas: ruta -> lista de paginas (listados) o dict (recurso) o RespuestaFalsa(s) a servir."""

    def __init__(self, rutas: dict):
        self.rutas = rutas
        self.pedidos: list[str] = []

    @classmethod
    def desde_fixture(cls, nombre: str) -> SesionFalsa:
        return cls(json.loads((FIXTURES / nombre).read_text(encoding="utf-8")))

    def get(self, url, params=None, headers=None, timeout=None):
        self.pedidos.append(url)
        analizada = urlparse(url)
        ruta = analizada.path
        pagina = int(parse_qs(analizada.query).get("page", ["1"])[0])
        destino = self.rutas.get(ruta)
        if isinstance(destino, Exception):
            raise destino
        if destino is None:
            return RespuestaFalsa(404, {"message": "Not Found"})
        if isinstance(destino, list) and destino and isinstance(destino[0], RespuestaFalsa):
            return destino.pop(0) if len(destino) > 1 else destino[0]
        if isinstance(destino, dict):
            return RespuestaFalsa(200, destino)
        links = {}
        if pagina < len(destino):
            links["next"] = {"url": f"{BASE}{ruta}?page={pagina + 1}"}
        return RespuestaFalsa(200, destino[pagina - 1], links=links)


def error_red() -> requests.ConnectionError:
    return requests.ConnectionError("sin red")
