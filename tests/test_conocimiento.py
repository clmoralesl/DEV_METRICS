import hashlib
import re

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from devmetrics.conocimiento import (
    TIPO_FUENTE_INTERNA,
    cargar_documentos,
    crear_indice_interno,
    indexar_conocimiento,
    recuperar_para_proyecto,
    segmentar_conocimiento,
)
from devmetrics.indexacion import IndiceVectorial
from devmetrics.perfiles import segmentar

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


def _escribir(ruta, nombre, cabecera, cuerpo="Texto del documento."):
    (ruta / nombre).write_text(f"---\n{cabecera}\n---\n{cuerpo}\n", encoding="utf-8")


CABECERA_OK = "categoria: requerimiento\ndocumento: req-x\ntitulo: Requerimiento X\narquetipos:"


def test_cargar_lee_cabecera_y_normaliza(tmp_path):
    for a in ("druid", "cleric"):
        _escribir(
            tmp_path,
            f"{a}.md",
            f"categoria: arquetipo\ndocumento: arquetipo-{a}\ntitulo: {a}\narquetipos: {a}",
        )
    _escribir(
        tmp_path,
        "a.md",
        CABECERA_OK.replace("arquetipos:", "arquetipos: Druid, Cleric"),
        "Cuerpo A",
    )
    doc = next(d for d in cargar_documentos(tmp_path) if d.metadata["origen"] == "a.md")
    assert doc.page_content == "Cuerpo A"
    assert doc.metadata["categoria"] == "requerimiento"
    assert doc.metadata["arquetipos"] == "druid,cleric"
    assert doc.metadata["tipo_fuente"] == TIPO_FUENTE_INTERNA
    assert doc.metadata["origen"] == "a.md"


@pytest.mark.parametrize(
    "contenido, mensaje",
    [
        ("sin cabecera", "falta la cabecera"),
        ("---\ncategoria: criterio\n", "no se cierra"),
        ("---\ncategoria: criterio\n---\ntexto", "faltan metadatos"),
        ("---\ncategoria: otra\ndocumento: d\ntitulo: T\n---\ntexto", "categoria desconocida"),
    ],
)
def test_cargar_rechaza_documentos_mal_formados(tmp_path, contenido, mensaje):
    (tmp_path / "x.md").write_text(contenido, encoding="utf-8")
    with pytest.raises(ValueError, match=mensaje):
        cargar_documentos(tmp_path)


def test_cargar_rechaza_identificadores_repetidos(tmp_path):
    _escribir(tmp_path, "a.md", CABECERA_OK)
    _escribir(tmp_path, "b.md", CABECERA_OK)
    with pytest.raises(ValueError, match="repetidos"):
        cargar_documentos(tmp_path)


def test_segmentar_antepone_titulo_y_asigna_ids_estables(tmp_path):
    cuerpo = "\n\n".join(f"Parrafo {i} " + "palabra " * 40 for i in range(8))
    _escribir(tmp_path, "a.md", CABECERA_OK, cuerpo)
    chunks = segmentar_conocimiento(cargar_documentos(tmp_path))
    assert len(chunks) > 1
    assert all(c.page_content.startswith("[Requerimiento X]") for c in chunks)
    assert [c.metadata["id"] for c in chunks] == [
        f"{TIPO_FUENTE_INTERNA}|req-x|{i}" for i in range(len(chunks))
    ]
    assert {c.metadata["n_chunks"] for c in chunks} == {len(chunks)}


def test_indexar_es_idempotente_y_actualiza(tmp_path):
    _escribir(tmp_path, "a.md", CABECERA_OK, "version uno")
    indice = crear_indice_interno(EmbeddingsBolsa(), ruta=None)
    assert indexar_conocimiento(indice, tmp_path).nuevos == 1
    assert indexar_conocimiento(indice, tmp_path).sin_cambios == 1
    _escribir(tmp_path, "a.md", CABECERA_OK, "version dos")
    r = indexar_conocimiento(indice, tmp_path)
    assert (r.actualizados, indice.contar()) == (1, 1)


def test_filtro_por_categoria(tmp_path):
    _escribir(tmp_path, "a.md", CABECERA_OK, "migracion a la nube")
    _escribir(
        tmp_path,
        "b.md",
        "categoria: arquetipo\ndocumento: arquetipo-druid\ntitulo: Druid\narquetipos: druid",
        "migracion a la nube",
    )
    indice = crear_indice_interno(EmbeddingsBolsa(), ruta=None)
    indexar_conocimiento(indice, tmp_path)
    r = indice.consultar("migracion", k=5, filtros={"categoria": "arquetipo"})
    assert [x.metadatos["documento"] for x in r] == ["arquetipo-druid"]


def test_la_base_interna_del_repositorio_es_valida():
    docs = cargar_documentos()
    por_categoria = {d.metadata["categoria"] for d in docs}
    assert por_categoria == {"requerimiento", "arquetipo", "criterio"}
    declarados = {a for d in docs for a in d.metadata["arquetipos"].split(",") if a}
    definidos = {
        d.metadata["documento"].removeprefix("arquetipo-")
        for d in docs
        if d.metadata["categoria"] == "arquetipo"
    }
    assert declarados <= definidos == {"druid", "cleric", "bard"}


def _perfil(dev, texto):
    return Document(
        page_content=f"Actividad de {dev} en org/facturacion (commits)\n{texto}",
        metadata={
            "desarrollador": dev,
            "repositorio": "org/facturacion",
            "tipo_fuente": "commits",
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-03-01",
        },
    )


def indices():
    emb = EmbeddingsBolsa()
    conocimiento = crear_indice_interno(emb, ruta=None)
    indexar_conocimiento(conocimiento)
    perfiles = IndiceVectorial(emb, ruta=None)
    perfiles.indexar(
        segmentar(
            [
                _perfil(
                    "ana",
                    "[2026-01-05] commit a1: corrige bug [archivos: tests/t.py]\n"
                    "[2026-01-09] reviso el PR #4 de otra persona: APPROVED",
                ),
                _perfil(
                    "beto",
                    "[2026-01-06] commit b2: agrega pipeline [archivos: Dockerfile, infra/main.tf]",
                ),
                _perfil(
                    "carla",
                    "[2026-01-07] commit c3: documentacion y guias [archivos: README.md]",
                ),
            ]
        )
    )
    return conocimiento, perfiles


def test_consulta_de_perfil_adecuado_recupera_requerimiento_y_perfiles():
    conocimiento, perfiles = indices()
    ctx = recuperar_para_proyecto(
        "perfil adecuado para estabilizar los microservicios de facturacion con errores",
        conocimiento,
        perfiles,
        k_perfiles=2,
    )
    assert [r.metadatos["documento"] for r in ctx.requerimientos] == [
        "req-estabilizacion-microservicios"
    ]
    assert {a.metadatos["documento"] for a in ctx.arquetipos} == {
        "arquetipo-cleric",
        "arquetipo-druid",
    }
    # El orden de los perfiles depende del modelo: se comprueba con embeddings reales en
    # tests/test_conocimiento_integracion.py.
    assert len(ctx.perfiles) == 2
    assert {p.metadatos["tipo_fuente"] for p in ctx.perfiles} == {"commits"}


def test_otro_proyecto_recupera_otro_requerimiento_y_perfil():
    conocimiento, perfiles = indices()
    ctx = recuperar_para_proyecto(
        "perfil adecuado para el portal de documentacion y guias",
        conocimiento,
        perfiles,
        k_perfiles=1,
    )
    assert ctx.requerimientos[0].metadatos["documento"] == "req-portal-documentacion"
    assert {a.metadatos["documento"] for a in ctx.arquetipos} == {"arquetipo-bard"}
    assert len(ctx.perfiles) == 1


def test_sin_requerimientos_no_falla():
    vacio = crear_indice_interno(EmbeddingsBolsa(), ruta=None)
    ctx = recuperar_para_proyecto(
        "cualquier cosa", vacio, IndiceVectorial(EmbeddingsBolsa(), ruta=None)
    )
    assert ctx.requerimientos == [] and ctx.arquetipos == [] and ctx.perfiles == []


def test_cargar_rechaza_arquetipo_sin_definicion(tmp_path):
    _escribir(tmp_path, "a.md", CABECERA_OK.replace("arquetipos:", "arquetipos: druid"))
    with pytest.raises(ValueError, match="no tiene documento"):
        cargar_documentos(tmp_path)


def test_distancia_maxima_descarta_requerimientos_lejanos():
    conocimiento, perfiles = indices()
    consulta = "estabilizar microservicios de facturacion"
    ctx = recuperar_para_proyecto(consulta, conocimiento, perfiles, distancia_maxima=2.0)
    assert ctx.requerimientos and ctx.perfiles
    ctx = recuperar_para_proyecto(consulta, conocimiento, perfiles, distancia_maxima=-1.0)
    assert ctx.requerimientos == [] and ctx.arquetipos == [] and ctx.perfiles == []


def test_filtros_rechaza_claves_con_parametro_propio():
    conocimiento, _ = indices()
    with pytest.raises(ValueError, match="parametro propio"):
        conocimiento.consultar("x", filtros={"tipo_fuente": "a"})


def test_indice_exige_claves_de_grupo_y_las_valida():
    with pytest.raises(ValueError, match="clave de grupo"):
        IndiceVectorial(EmbeddingsBolsa(), ruta=None, claves_grupo=())
    indice = IndiceVectorial(EmbeddingsBolsa(), ruta=None, claves_grupo=("documento",))
    with pytest.raises(ValueError, match="obligatorios: documento"):
        indice.indexar([Document(page_content="x", metadata={"id": "1"})])
