"""Recuperacion de la fuente interna con embeddings reales: solo con DEVMETRICS_INTEGRACION=1."""

import os

import pytest
from langchain_core.documents import Document

from devmetrics.conocimiento import (
    ContextoProyecto,
    crear_indice_interno,
    indexar_conocimiento,
    recuperar_para_proyecto,
)
from devmetrics.indexacion import IndiceVectorial
from devmetrics.llm import ModeloEmbeddings
from devmetrics.perfiles import segmentar

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVMETRICS_INTEGRACION") != "1", reason="integracion desactivada"
)

PERFILES = {
    "ana": (
        "[2026-01-05] commit a1b2c3d: fix bug en el servicio de pagos [archivos: src/pagos.py]\n"
        "[2026-01-08] commit d4e5f6a: corrige regresion y agrega prueba [archivos: tests/t.py]\n"
        "[2026-01-09] reviso el PR #4 de otra persona: CHANGES_REQUESTED"
    ),
    "beto": (
        "[2026-01-05] commit b1: agrega pipeline de despliegue [archivos: Dockerfile, main.tf]\n"
        "[2026-01-08] commit b2: migracion de base de datos [archivos: migrations/1.sql]"
    ),
    "carla": (
        "[2026-01-05] commit c1: guia de inicio de la API [archivos: README.md, docs/guia.md]\n"
        "[2026-01-08] commit c2: estilos y componentes de la interfaz [archivos: src/app.css]"
    ),
}


def test_la_consulta_recupera_requerimiento_y_perfil_relacionado(tmp_path):
    emb = ModeloEmbeddings()
    conocimiento = crear_indice_interno(emb, ruta=str(tmp_path / "chroma"))
    indexar_conocimiento(conocimiento)
    perfiles = IndiceVectorial(emb, ruta=None)
    perfiles.indexar(
        segmentar(
            [
                Document(
                    page_content=f"Actividad de {dev} en org/facturacion (commits)\n{texto}",
                    metadata={
                        "desarrollador": dev,
                        "repositorio": "org/facturacion",
                        "tipo_fuente": "commits",
                        "fecha_desde": "2026-01-05",
                        "fecha_hasta": "2026-01-09",
                    },
                )
                for dev, texto in PERFILES.items()
            ]
        )
    )
    casos = {
        "perfil adecuado para estabilizar microservicios con errores": (
            "req-estabilizacion-microservicios",
            "ana",
        ),
        "perfil adecuado para el portal de documentacion": ("req-portal-documentacion", "carla"),
        "perfil adecuado para migrar la plataforma a la nube": ("req-migracion-nube", "beto"),
    }
    for consulta, (requerimiento, dev) in casos.items():
        ctx = recuperar_para_proyecto(consulta, conocimiento, perfiles, k_perfiles=1)
        assert ctx.requerimientos[0].metadatos["documento"] == requerimiento, consulta
        assert ctx.perfiles[0].metadatos["desarrollador"] == dev, consulta

    # La consulta ajena queda mas lejos que las propias: un umbral entre ambas la descarta.
    ajena = "receta de cocina con harina y huevos"
    d_ajena = recuperar_para_proyecto(ajena, conocimiento, perfiles).requerimientos[0].distancia
    d_propias = [
        recuperar_para_proyecto(c, conocimiento, perfiles).requerimientos[0].distancia
        for c in casos
    ]
    assert max(d_propias) < d_ajena
    umbral = (max(d_propias) + d_ajena) / 2
    assert recuperar_para_proyecto(ajena, conocimiento, perfiles, distancia_maxima=umbral) == (
        ContextoProyecto()
    )
