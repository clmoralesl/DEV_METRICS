from __future__ import annotations

import json
import os
from pathlib import Path

from .esquema import DatosRepo


class CacheLocal:
    """Un archivo JSON por repositorio bajo data/github/."""

    def __init__(self, directorio: str | os.PathLike = "data/github"):
        self.directorio = Path(directorio)

    def ruta(self, repo: str) -> Path:
        # "~" no puede aparecer en nombres de GitHub, asi que la clave no colisiona
        return self.directorio / f"{repo.casefold().replace('/', '~')}.json"

    def cargar(self, repo: str) -> DatosRepo | None:
        try:
            texto = self.ruta(repo).read_text(encoding="utf-8")
            return DatosRepo.desde_dict(json.loads(texto))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def guardar(self, datos: DatosRepo) -> Path:
        destino = self.ruta(datos.repo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".tmp")
        temporal.write_text(
            json.dumps(datos.a_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(temporal, destino)
        return destino
