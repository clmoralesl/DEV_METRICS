"""Experimento de chunk_size y chunk_overlap sobre documentos de perfil.

Para los desarrolladores mas activos de un repositorio ya ingerido, arma los documentos de
perfil, los segmenta con cada configuracion y recupera por similitud (coseno, filtrando por
desarrollador) los chunks de una consulta por tipo de cambio. La relevancia sale de la
heuristica de arquetipos.clasificar_cambio, independiente del embedding.

Metricas por configuracion (promedio sobre pares desarrollador x tipo de cambio):
- precision: parte de las lineas de commit recuperadas que son del tipo consultado.
- cobertura: parte de los commits del tipo (del desarrollador) que aparecen en lo recuperado.
- F1: media armonica de precision y cobertura.
- contexto: caracteres recuperados (costo en el prompt).

Requiere la ingesta previa (el script lee la cache, no llama a la API):
  python scripts/ingestar.py pallets/click --data-dir data/github_chunking --max-commits 400
    --max-prs 30 --max-issues 30 --max-comentarios 50
Uso: python scripts/experimento_chunking.py [--repo pallets/click] [--desarrolladores 5] [-k 4]
Elige los N desarrolladores con mas commits en la cache y no imprime sus logins.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from devmetrics.arquetipos import Commit as CommitSenal  # noqa: E402
from devmetrics.arquetipos import cargar, clasificar_cambio  # noqa: E402
from devmetrics.ingesta import CacheLocal  # noqa: E402
from devmetrics.llm.embeddings import ModeloEmbeddings  # noqa: E402
from devmetrics.perfiles import ConfigChunking, documentos_de, segmentar  # noqa: E402

CONFIGURACIONES = [
    ConfigChunking(300, 30),
    ConfigChunking(600, 0),
    ConfigChunking(600, 120),
    ConfigChunking(1000, 100),
    ConfigChunking(2000, 200),
]
CONSULTAS = {
    "correccion": "correccion de errores y bugs",
    "funcionalidad": "nuevas funcionalidades y caracteristicas",
    "documentacion": "cambios en la documentacion",
    "refactor": "refactorizacion y limpieza del codigo",
}
MIN_COMMITS_TIPO = 3
SHA = re.compile(r"commit ([0-9a-f]{7}):")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="pallets/click")
    ap.add_argument("--desarrolladores", type=int, default=5)
    ap.add_argument("-k", type=int, default=4)
    ap.add_argument("--data-dir", default="data/github_chunking")
    args = ap.parse_args()

    datos = CacheLocal(str(RAIZ / args.data_dir)).cargar(args.repo)
    if datos is None:
        sys.exit(
            f"{args.repo} no esta en {args.data_dir}/: ejecutar scripts/ingestar.py "
            f"{args.repo} --data-dir {args.data_dir} --max-commits 400 primero"
        )
    config = cargar()
    cuentas = Counter(c.autor.casefold() for c in datos.commits if c.autor)
    logins = [a for a, _ in cuentas.most_common() if "[bot]" not in a][: args.desarrolladores]

    tipo_de_sha = {
        c.sha[:7]: clasificar_cambio(
            CommitSenal(c.mensaje, tuple(a.ruta for a in c.archivos), c.repo), config
        )
        for c in datos.commits
    }
    commits_por_dev_tipo: dict[tuple[str, str], set[str]] = {}
    for c in datos.commits:
        if c.autor and c.autor.casefold() in logins:
            commits_por_dev_tipo.setdefault((c.autor.casefold(), tipo_de_sha[c.sha[:7]]), set())
            commits_por_dev_tipo[(c.autor.casefold(), tipo_de_sha[c.sha[:7]])].add(c.sha[:7])

    modelo = ModeloEmbeddings()
    consultas_emb = {t: np.array(modelo.embed_query(q)) for t, q in CONSULTAS.items()}
    print(f"repo={args.repo} commits={len(datos.commits)} desarrolladores={len(logins)} k={args.k}")
    print(
        "| chunk_size | chunk_overlap | chunks | caracteres/chunk | precision | cobertura "
        "| F1 | contexto |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for cfg in CONFIGURACIONES:
        chunks_por_dev = {}
        for login in logins:
            docs = [
                d for d in documentos_de(login, [datos]) if d.metadata["tipo_fuente"] == "commits"
            ]
            chunks_por_dev[login] = segmentar(docs, cfg)
        todos = [c for cs in chunks_por_dev.values() for c in cs]
        emb = {
            id(c): v for c, v in zip(todos, modelo.embed_documents([c.page_content for c in todos]))
        }
        precisiones, coberturas, contextos = [], [], []
        for login, chunks in chunks_por_dev.items():
            matriz = np.array([emb[id(c)] for c in chunks])
            matriz = matriz / np.linalg.norm(matriz, axis=1, keepdims=True)
            for tipo, q in consultas_emb.items():
                objetivo = commits_por_dev_tipo.get((login, tipo), set())
                if len(objetivo) < MIN_COMMITS_TIPO:
                    continue
                orden = np.argsort(-(matriz @ (q / np.linalg.norm(q))))[: args.k]
                texto = "\n".join(chunks[i].page_content for i in orden)
                recuperados = set(SHA.findall(texto))
                precisiones.append(
                    sum(tipo_de_sha[s] == tipo for s in recuperados) / len(recuperados)
                    if recuperados
                    else 0.0
                )
                coberturas.append(len(objetivo & recuperados) / len(objetivo))
                contextos.append(len(texto))
        if not precisiones:
            sys.exit("sin pares desarrollador x tipo con commits suficientes: usar mas commits")
        medio = statistics.mean(len(c.page_content) for c in todos)
        p_, c_ = statistics.mean(precisiones), statistics.mean(coberturas)
        f1 = 2 * p_ * c_ / (p_ + c_) if p_ + c_ else 0.0
        print(
            f"| {cfg.chunk_size} | {cfg.chunk_overlap} | {len(todos)} | {medio:.0f} | "
            f"{p_:.3f} | {c_:.3f} | {f1:.3f} | {statistics.mean(contextos):.0f} |"
        )

    print(f"pares evaluados: {len(precisiones)}")


if __name__ == "__main__":
    main()
