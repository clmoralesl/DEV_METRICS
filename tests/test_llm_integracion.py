"""Pruebas de integracion opcionales: se omiten salvo con DEVMETRICS_INTEGRACION=1.

Gemini requiere GOOGLE_API_KEY, Ollama un servidor activo con el modelo descargado y los
embeddings la descarga unica del modelo (unos 220 MB).
"""

import os

import pytest
from dotenv import load_dotenv

from devmetrics.llm import ClienteLLM, ConfigLLM, ModeloEmbeddings

load_dotenv()
pytestmark = pytest.mark.skipif(
    os.environ.get("DEVMETRICS_INTEGRACION") != "1", reason="integracion desactivada"
)

DOCUMENTOS = {
    "bd": "Optimizacion de consultas SQL y migraciones de la base de datos",
    "fe": "Mejoras de la interfaz web con componentes React y estilos CSS",
    "rev": "Revision de pull requests y correccion de errores reportados por usuarios",
    "doc": "Redaccion de la guia de instalacion y documentacion del proyecto",
}
CONSULTAS = {
    "bd": "quien trabaja con bases de datos",
    "fe": "desarrolladores de frontend",
    "rev": "quien revisa codigo y arregla bugs",
    "doc": "quien escribe documentacion",
}


def _coseno(a, b):
    punto = sum(x * y for x, y in zip(a, b, strict=True))
    return punto / (sum(x * x for x in a) ** 0.5 * sum(y * y for y in b) ** 0.5)


def _solo(proveedor):
    return ClienteLLM(ConfigLLM(proveedor=proveedor, respaldo=None, max_tokens=64))


def test_gemini_responde():
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("sin GOOGLE_API_KEY")
    assert _solo("gemini").invocar("Responde solo con la palabra: listo")


def test_ollama_responde():
    if os.environ.get("DEVMETRICS_OLLAMA_MODEL") is None:
        pytest.skip("defina DEVMETRICS_OLLAMA_MODEL con un modelo descargado")
    config = ConfigLLM.desde_entorno()
    cliente = ClienteLLM(
        ConfigLLM(proveedor="ollama", respaldo=None, modelo_ollama=config.modelo_ollama)
    )
    assert cliente.invocar("Responde solo con la palabra: listo")


def test_recuperacion_en_espanol():
    modelo = ModeloEmbeddings()
    ids = list(DOCUMENTOS)
    vectores = modelo.embed_documents([DOCUMENTOS[i] for i in ids])
    aciertos = 0
    for clave, consulta in CONSULTAS.items():
        q = modelo.embed_query(consulta)
        puntajes = [_coseno(q, v) for v in vectores]
        aciertos += ids[puntajes.index(max(puntajes))] == clave
    assert aciertos == len(CONSULTAS)
