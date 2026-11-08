"""Embeddings locales y multilingues (fastembed, ONNX, sin torch ni red tras la descarga)."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _usar_almacen_del_sistema() -> None:
    """Confia en el almacen de certificados del sistema (antivirus o proxy con HTTPS)."""
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


class ModeloEmbeddings(Embeddings):
    """Adaptador de fastembed a la interfaz Embeddings de LangChain."""

    def __init__(self, modelo: str = MODELO_EMBEDDINGS, cache_dir: str | None = None):
        self.modelo = modelo
        self._cache_dir = cache_dir
        self._motor = None

    def _cargar(self):
        if self._motor is None:
            _usar_almacen_del_sistema()
            from fastembed import TextEmbedding

            self._motor = TextEmbedding(model_name=self.modelo, cache_dir=self._cache_dir)
        return self._motor

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._cargar().embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
