"""Indexacion con embeddings reales: se omite salvo con DEVMETRICS_INTEGRACION=1."""

import os

import pytest
from langchain_core.documents import Document

from devmetrics.indexacion import IndiceVectorial
from devmetrics.llm import ModeloEmbeddings
from devmetrics.perfiles import segmentar

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVMETRICS_INTEGRACION") != "1", reason="integracion desactivada"
)


def _doc(dev, tipo, texto):
    return Document(
        page_content=texto,
        metadata={
            "desarrollador": dev,
            "repositorio": "org/api",
            "tipo_fuente": tipo,
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-02-01",
        },
    )


def test_consulta_semantica_con_filtro_y_reindexado_idempotente(tmp_path):
    docs = segmentar(
        [
            _doc("ana", "commits", "Optimizacion de consultas SQL y migraciones de base de datos"),
            _doc("beto", "commits", "Componentes React y estilos CSS de la interfaz web"),
            _doc("beto", "revisiones", "Revision de pull requests y correccion de errores"),
        ]
    )
    indice = IndiceVectorial(ModeloEmbeddings(), ruta=str(tmp_path / "chroma"))
    indice.indexar(docs)
    assert (
        indice.consultar("quien trabaja con bases de datos", k=1)[0].metadatos["desarrollador"]
        == "ana"
    )
    solo_beto = indice.consultar("quien trabaja con bases de datos", k=3, desarrollador="beto")
    assert {r.metadatos["desarrollador"] for r in solo_beto} == {"beto"}
    assert indice.indexar(docs).sin_cambios == 3
    assert indice.contar() == 3
