"""Embeddings deterministas para pruebas."""

import hashlib
import re

from langchain_core.embeddings import Embeddings

DIM = 128


class EmbeddingsBolsa(Embeddings):
    """Bolsa de palabras con hashing: determinista y con similitud lexica real."""

    def _vec(self, texto):
        v = [0.0] * DIM
        for p in re.findall(r"\w+", texto.casefold()):
            v[int(hashlib.md5(p.encode()).hexdigest(), 16) % DIM] += 1.0
        return v

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)
