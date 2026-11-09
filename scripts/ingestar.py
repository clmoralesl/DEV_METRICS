"""Ingesta reproducible de repositorios publicos desde la API de GitHub a data/github/.

Uso: python scripts/ingestar.py propietario/repo [propietario/repo ...] [--archivo lista.txt]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devmetrics.ingesta import CacheLocal, ClienteGitHub, Limites, ingerir  # noqa: E402


def _leer_lista(ruta: str) -> list[str]:
    lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
    return [x.strip() for x in lineas if x.strip() and not x.lstrip().startswith("#")]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repos", nargs="*", help="repositorios como propietario/repo")
    p.add_argument("--archivo", help="archivo de texto con un repositorio por linea")
    p.add_argument("--data-dir", default="data/github")
    p.add_argument("--max-commits", type=int, default=200)
    p.add_argument("--max-prs", type=int, default=100)
    p.add_argument("--max-issues", type=int, default=200)
    p.add_argument("--max-comentarios", type=int, default=500)
    p.add_argument("--desde", help="solo commits desde esta fecha ISO 8601")
    p.add_argument("--refrescar", action="store_true", help="ignora la cache existente")
    args = p.parse_args(argv)

    repos = list(args.repos) + (_leer_lista(args.archivo) if args.archivo else [])
    if not repos:
        p.error("indique al menos un repositorio")

    load_dotenv()
    try:
        import truststore

        truststore.inject_into_ssl()  # antivirus o proxy que reemplaza el certificado HTTPS
    except ImportError:
        pass
    token = os.environ.get("GITHUB_TOKEN") or None
    if token is None:
        print(
            "aviso: GITHUB_TOKEN no definido; el limite sin autenticar (60 solicitudes por hora) "
            "no alcanza: cada commit y cada PR cuestan una solicitud",
            file=sys.stderr,
        )

    limites = Limites(
        args.max_commits, args.max_prs, args.max_issues, args.max_comentarios, args.desde
    )
    cliente = ClienteGitHub(token)
    res = ingerir(
        repos, cliente, CacheLocal(args.data_dir), limites=limites, refrescar=args.refrescar
    )

    for repo, d in res.datos.items():
        origen = "cache" if repo in res.desde_cache else "API"
        print(
            f"{repo} [{origen}]: {len(d.commits)} commits, {len(d.pull_requests)} PR, "
            f"{len(d.revisiones)} revisiones, {len(d.issues)} issues, "
            f"{len(d.comentarios)} comentarios"
        )
    for repo, motivo in res.errores.items():
        print(f"{repo}: ERROR {motivo}", file=sys.stderr)
    if res.pendientes:
        print(f"pendientes por limite de tasa: {', '.join(res.pendientes)}", file=sys.stderr)
    print(f"solicitudes a la API: {cliente.llamadas}")
    return 1 if res.errores else 0


if __name__ == "__main__":
    raise SystemExit(main())
