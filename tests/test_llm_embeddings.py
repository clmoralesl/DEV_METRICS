import numpy as np

from devmetrics.llm import ModeloEmbeddings


class MotorSimulado:
    def embed(self, textos):
        for t in textos:
            yield np.array([float(len(t)), 1.0], dtype=np.float32)


def modelo():
    m = ModeloEmbeddings()
    m._motor = MotorSimulado()
    return m


def test_embed_documents_devuelve_listas_de_float():
    vectores = modelo().embed_documents(["ab", "abcd"])
    assert vectores == [[2.0, 1.0], [4.0, 1.0]]
    assert all(isinstance(x, float) for x in vectores[0])


def test_embed_query_devuelve_un_vector():
    assert modelo().embed_query("abc") == [3.0, 1.0]
