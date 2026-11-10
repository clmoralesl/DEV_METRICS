"""Fuente interna: base de conocimiento de la organizacion (requerimientos, arquetipos, criterios).

Los documentos son archivos Markdown con una cabecera `clave: valor` entre lineas `---`. Se
indexan en una coleccion propia con el mismo `IndiceVectorial` que los perfiles, agrupados por
(tipo_fuente, documento).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from devmetrics.indexacion import RUTA_POR_DEFECTO, IndiceVectorial, ResultadoConsulta
from devmetrics.perfiles import CONFIG_CHUNKING, ConfigChunking

RUTA_CONOCIMIENTO = "conocimiento"
COLECCION_INTERNA = "conocimiento"
TIPO_FUENTE_INTERNA = "conocimiento_interno"
CLAVES_GRUPO_INTERNO = ("tipo_fuente", "documento")
CATEGORIAS = ("requerimiento", "arquetipo", "criterio")
_OBLIGATORIOS = ("categoria", "documento", "titulo")


def _leer(ruta: Path) -> Document:
    texto = ruta.read_text(encoding="utf-8").lstrip("﻿")
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        raise ValueError(f"{ruta.name}: falta la cabecera de metadatos")
    try:
        fin = next(i for i in range(1, len(lineas)) if lineas[i].strip() == "---")
    except StopIteration:
        raise ValueError(f"{ruta.name}: la cabecera no se cierra") from None
    meta: dict[str, str] = {}
    for linea in lineas[1:fin]:
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            meta[clave.strip()] = valor.strip()
    faltan = [k for k in _OBLIGATORIOS if not meta.get(k)]
    if faltan:
        raise ValueError(f"{ruta.name}: faltan metadatos: {', '.join(faltan)}")
    if meta["categoria"] not in CATEGORIAS:
        raise ValueError(f"{ruta.name}: categoria desconocida: {meta['categoria']!r}")
    meta["arquetipos"] = ",".join(
        a.strip().casefold() for a in meta.get("arquetipos", "").split(",") if a.strip()
    )
    meta["tipo_fuente"] = TIPO_FUENTE_INTERNA
    meta["origen"] = ruta.name
    return Document(page_content="\n".join(lineas[fin + 1 :]).strip(), metadata=meta)


def cargar_documentos(ruta: str | Path = RUTA_CONOCIMIENTO) -> list[Document]:
    """Documentos de `ruta/*.md`, ordenados por nombre. Falla si un documento esta mal formado
    o si dos comparten el identificador `documento`."""
    docs = [_leer(p) for p in sorted(Path(ruta).glob("*.md"))]
    ids = [d.metadata["documento"] for d in docs]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise ValueError(f"identificadores de documento repetidos: {', '.join(sorted(repetidos))}")
    definidos = {i for d, i in zip(docs, ids) if d.metadata["categoria"] == "arquetipo"}
    for d in docs:
        for a in filter(None, d.metadata["arquetipos"].split(",")):
            if f"arquetipo-{a}" not in definidos:
                raise ValueError(
                    f"{d.metadata['origen']}: el arquetipo {a!r} no tiene documento 'arquetipo-{a}'"
                )
    return docs


def segmentar_conocimiento(
    documentos: list[Document], config: ConfigChunking = CONFIG_CHUNKING
) -> list[Document]:
    """Chunks por seccion cuando es posible. Cada chunk antepone el titulo del documento porque
    los chunks posteriores al primero no repetirian de que documento proceden."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=["\n## ", "\n\n", "\n", " ", ""],
    )
    chunks: list[Document] = []
    for doc in documentos:
        partes = splitter.split_text(doc.page_content)
        for i, texto in enumerate(partes):
            chunks.append(
                Document(
                    page_content=f"[{doc.metadata['titulo']}]\n{texto}",
                    metadata={
                        **doc.metadata,
                        "chunk": i,
                        "n_chunks": len(partes),
                        "id": f"{TIPO_FUENTE_INTERNA}|{doc.metadata['documento']}|{i}",
                    },
                )
            )
    return chunks


def crear_indice_interno(
    embeddings: Embeddings, ruta: str | None = RUTA_POR_DEFECTO
) -> IndiceVectorial:
    return IndiceVectorial(
        embeddings, ruta=ruta, coleccion=COLECCION_INTERNA, claves_grupo=CLAVES_GRUPO_INTERNO
    )


def indexar_conocimiento(indice: IndiceVectorial, ruta: str | Path = RUTA_CONOCIMIENTO):
    """Carga, segmenta e indexa la base interna (idempotente). Devuelve el ResultadoIndexado."""
    return indice.indexar(segmentar_conocimiento(cargar_documentos(ruta)))


@dataclass(frozen=True)
class ContextoProyecto:
    """Contexto para recomendar perfiles: requerimientos, definiciones de arquetipo y perfiles."""

    requerimientos: list[ResultadoConsulta] = field(default_factory=list)
    arquetipos: list[ResultadoConsulta] = field(default_factory=list)
    perfiles: list[ResultadoConsulta] = field(default_factory=list)


def recuperar_para_proyecto(
    consulta: str,
    conocimiento: IndiceVectorial,
    perfiles: IndiceVectorial,
    *,
    k_requerimientos: int = 1,
    k_perfiles: int = 4,
    distancia_maxima: float | None = None,
) -> ContextoProyecto:
    """Recuperacion en dos pasos para "perfil adecuado para este proyecto".

    1) El requerimiento mas cercano a la consulta (y sus arquetipos, declarados en su cabecera).
    2) La definicion de cada uno de esos arquetipos.
    3) Los perfiles cuyo texto de actividad se acerca a esas definiciones y a la consulta.
    Las definiciones aportan el vocabulario de la actividad (Dockerfile, pruebas, README...) que
    el requerimiento solo describe en lenguaje de negocio.

    `distancia_maxima` (coseno) descarta requerimientos lejanos: sin requerimiento cercano el
    contexto queda vacio y el agente puede responder "sin informacion". Sin umbral siempre se
    devuelve el mas cercano. Los perfiles son chunks: varios pueden ser del mismo desarrollador;
    agrupar por (desarrollador, repositorio) es tarea del agente.
    """
    reqs = conocimiento.consultar(
        consulta, k=k_requerimientos, filtros={"categoria": "requerimiento"}
    )
    if distancia_maxima is not None:
        reqs = [r for r in reqs if r.distancia <= distancia_maxima]
    if not reqs:
        return ContextoProyecto()
    arquetipos: list[ResultadoConsulta] = []
    vistos: set[str] = set()
    for r in reqs:
        for a in r.metadatos.get("arquetipos", "").split(","):
            if a and a not in vistos:
                vistos.add(a)
                arquetipos += conocimiento.consultar(
                    f"arquetipo {a}", k=1, filtros={"documento": f"arquetipo-{a}"}
                )
    texto = "\n".join([consulta, *(a.texto for a in arquetipos)])
    return ContextoProyecto(reqs, arquetipos, perfiles.consultar(texto, k=k_perfiles))
