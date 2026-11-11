"""Indexa la base de conocimiento interna (conocimiento/*.md) en la coleccion "conocimiento".

Uso: python scripts/indexar_conocimiento.py [--ruta conocimiento] [--indice data/chroma]
Es idempotente: volver a ejecutarlo solo recalcula los documentos que cambiaron.
"""

from __future__ import annotations

import argparse

from devmetrics.conocimiento import (
    RUTA_CONOCIMIENTO,
    crear_indice_interno,
    indexar_conocimiento,
)
from devmetrics.indexacion import RUTA_POR_DEFECTO
from devmetrics.llm import ModeloEmbeddings


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruta", default=RUTA_CONOCIMIENTO)
    ap.add_argument("--indice", default=RUTA_POR_DEFECTO)
    args = ap.parse_args(argv)
    indice = crear_indice_interno(ModeloEmbeddings(), ruta=args.indice)
    r = indexar_conocimiento(indice, args.ruta)
    print(
        f"nuevos={r.nuevos} actualizados={r.actualizados} sin_cambios={r.sin_cambios} "
        f"eliminados={r.eliminados} total={indice.contar()}"
    )


if __name__ == "__main__":
    main()
