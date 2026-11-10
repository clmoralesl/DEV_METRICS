"""Segmentacion de documentos de perfil con RecursiveCharacterTextSplitter."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(frozen=True)
class ConfigChunking:
    chunk_size: int
    chunk_overlap: int

    def __post_init__(self):
        if self.chunk_size <= 0 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("se requiere chunk_size > 0 y 0 <= chunk_overlap < chunk_size")


# Elegida con scripts/experimento_chunking.py (documentacion/pruebas.md): mejor F1 de precision
# y cobertura con un contexto de unos 2000 caracteres para k=4. Con 9 pares la ventaja del
# solapamiento sobre 600 sin solapar es una tendencia, no una diferencia comprobada.
CONFIG_CHUNKING = ConfigChunking(chunk_size=600, chunk_overlap=120)


def segmentar(
    documentos: list[Document], config: ConfigChunking = CONFIG_CHUNKING
) -> list[Document]:
    """Parte los documentos en chunks que conservan los metadatos y agregan su posicion.

    Se separa por lineas antes que por palabras para no cortar un evento a la mitad cuando
    es posible. La cabecera del documento (quien y donde) viaja solo en el primer chunk; los
    metadatos identifican a los demas: la capa de recuperacion debe propagarlos junto al texto.
    Cada chunk lleva un `id` estable (desarrollador|repositorio|tipo_fuente|posicion) para
    reindexar sin duplicados.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks: list[Document] = []
    for doc in documentos:
        partes = splitter.split_text(doc.page_content)
        for i, texto in enumerate(partes):
            chunks.append(
                Document(
                    page_content=texto,
                    metadata={
                        **doc.metadata,
                        "chunk": i,
                        "n_chunks": len(partes),
                        "id": "|".join(
                            str(doc.metadata[k])
                            for k in ("desarrollador", "repositorio", "tipo_fuente")
                        )
                        + f"|{i}",
                    },
                )
            )
    return chunks
