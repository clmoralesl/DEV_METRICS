import hashlib
import re

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from devmetrics.indexacion import IndiceVectorial
from devmetrics.perfiles import segmentar

DIM = 64


class EmbeddingsBolsa(Embeddings):
    """Bolsa de palabras con hashing: determinista y con similitud lexica real."""

    def __init__(self):
        self.llamadas = 0

    def _vec(self, texto):
        v = [0.0] * DIM
        for p in re.findall(r"\w+", texto.casefold()):
            v[int(hashlib.md5(p.encode()).hexdigest(), 16) % DIM] += 1.0
        return v

    def embed_documents(self, texts):
        self.llamadas += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def doc(dev, repo, tipo, texto, desde="2026-01-10", hasta="2026-02-20"):
    return Document(
        page_content=texto,
        metadata={
            "desarrollador": dev,
            "repositorio": repo,
            "tipo_fuente": tipo,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "n_eventos": 1,
        },
    )


def corpus():
    return segmentar(
        [
            doc("ana", "org/api", "commits", "corrige bug en el parser de configuracion"),
            doc(
                "ana",
                "org/api",
                "pull_requests",
                "pull request para documentar el README",
                "2026-03-01",
                "2026-03-15",
            ),
            doc(
                "beto",
                "org/api",
                "commits",
                "refactoriza el modulo de autenticacion",
                "2026-02-01",
                "2026-02-28",
            ),
            doc(
                "beto",
                "org/web",
                "revisiones",
                "reviso el PR de pruebas del parser",
                "2026-04-01",
                "2026-04-30",
            ),
        ]
    )


@pytest.fixture
def emb():
    return EmbeddingsBolsa()


@pytest.fixture
def indice(emb):
    return IndiceVectorial(emb, ruta=None)


def test_indexar_cuenta_y_consulta_por_similitud(indice):
    r = indice.indexar(corpus())
    assert (r.nuevos, r.sin_cambios, r.eliminados) == (4, 0, 0)
    assert indice.contar() == 4
    top = indice.consultar("bug del parser de configuracion", k=1)[0]
    assert top.metadatos["desarrollador"] == "ana"
    assert top.metadatos["tipo_fuente"] == "commits"
    assert top.id == "ana|org/api|commits|0"
    assert top.texto.startswith("corrige bug")


def test_resultado_propaga_metadatos_del_chunk(indice):
    indice.indexar(corpus())
    m = indice.consultar("autenticacion", k=1)[0].metadatos
    for clave in ("desarrollador", "repositorio", "tipo_fuente", "id", "chunk", "n_chunks"):
        assert clave in m


@pytest.mark.parametrize(
    "filtros,esperado",
    [
        ({"desarrollador": "beto"}, {"beto"}),
        ({"desarrollador": "BETO"}, {"beto"}),
        ({"repositorio": "org/web"}, {"beto"}),
        ({"tipo_fuente": "commits"}, {"ana", "beto"}),
        ({"desarrollador": "ana", "tipo_fuente": "pull_requests"}, {"ana"}),
    ],
)
def test_filtros_por_metadatos(indice, filtros, esperado):
    indice.indexar(corpus())
    res = indice.consultar("parser", k=10, **filtros)
    assert res and {r.metadatos["desarrollador"] for r in res} == esperado


def test_filtro_combinado_sin_coincidencias(indice):
    indice.indexar(corpus())
    assert indice.consultar("parser", desarrollador="ana", repositorio="org/web") == []


def test_filtro_no_deja_pasar_otros_aunque_sean_mas_similares(indice):
    indice.indexar(corpus())
    res = indice.consultar("reviso el PR de pruebas del parser", k=10, desarrollador="ana")
    assert {r.metadatos["desarrollador"] for r in res} == {"ana"}


def test_filtro_por_fecha_usa_solapamiento(indice):
    indice.indexar(corpus())
    marzo = indice.consultar("x", k=10, desde="2026-03-10", hasta="2026-03-31")
    assert [r.metadatos["desarrollador"] for r in marzo] == ["ana"]
    assert marzo[0].metadatos["tipo_fuente"] == "pull_requests"
    desde_abril = indice.consultar("x", k=10, desde="2026-04-15")
    assert [r.metadatos["repositorio"] for r in desde_abril] == ["org/web"]
    hasta_enero = indice.consultar("x", k=10, hasta="2026-01-31")
    assert {r.metadatos["desarrollador"] for r in hasta_enero} == {"ana"}


def test_fecha_invalida_y_k_invalido(indice):
    indice.indexar(corpus())
    with pytest.raises(ValueError):
        indice.consultar("x", desde="marzo")
    with pytest.raises(ValueError):
        indice.consultar("x", k=0)


def test_indice_vacio_devuelve_lista_vacia(indice):
    assert indice.consultar("lo que sea") == []


def test_reindexar_es_idempotente_y_no_recalcula_embeddings(indice, emb):
    indice.indexar(corpus())
    llamadas = emb.llamadas
    r = indice.indexar(corpus())
    assert (r.nuevos, r.actualizados, r.eliminados, r.sin_cambios) == (0, 0, 0, 4)
    assert indice.contar() == 4
    assert emb.llamadas == llamadas


def test_cambio_de_texto_actualiza_sin_duplicar(indice, emb):
    indice.indexar(corpus())
    cambiado = corpus()
    cambiado[0].page_content = "agrega soporte de logging estructurado"
    llamadas = emb.llamadas
    r = indice.indexar(cambiado)
    assert (r.actualizados, r.sin_cambios, r.nuevos) == (1, 3, 0)
    assert emb.llamadas == llamadas + 1
    assert indice.contar() == 4
    assert indice.consultar("logging estructurado", k=1)[0].id == "ana|org/api|commits|0"


def test_incremental_agrega_solo_lo_nuevo(indice):
    base = corpus()
    indice.indexar(base[:2])
    r = indice.indexar(base)
    assert (r.nuevos, r.sin_cambios) == (2, 2)
    assert indice.contar() == 4


def test_documento_que_se_acorta_elimina_chunks_obsoletos(indice):
    largo = "\n".join(
        f"[2026-01-{d:02d}] commit abc{d:04d}: cambio numero {d}" for d in range(1, 29)
    )
    indice.indexar(segmentar([doc("ana", "org/api", "commits", largo)]))
    antes = indice.contar()
    assert antes > 1
    r = indice.indexar(segmentar([doc("ana", "org/api", "commits", "un solo evento")]))
    assert r.eliminados == antes - 1
    assert indice.contar() == 1


def test_reindexar_un_grupo_no_toca_otros(indice):
    indice.indexar(corpus())
    indice.indexar(segmentar([doc("ana", "org/api", "commits", "texto nuevo de ana")]))
    assert indice.contar() == 4
    assert indice.consultar("autenticacion", k=1, desarrollador="beto")


def test_ids_repetidos_se_rechazan(indice):
    c = corpus()
    with pytest.raises(ValueError):
        indice.indexar([c[0], c[0]])


def test_persistencia_en_disco_conserva_y_no_duplica(tmp_path, emb):
    ruta = str(tmp_path / "chroma")
    IndiceVectorial(emb, ruta=ruta).indexar(corpus())
    otro = IndiceVectorial(emb, ruta=ruta)
    assert otro.contar() == 4
    assert otro.indexar(corpus()).sin_cambios == 4
    assert otro.contar() == 4


def test_cambio_solo_de_metadatos_se_actualiza(indice, emb):
    indice.indexar(corpus())
    cambiado = corpus()
    cambiado[0].metadata["fecha_hasta"] = "2026-06-30"
    r = indice.indexar(cambiado)
    assert (r.actualizados, r.sin_cambios) == (1, 3)
    assert indice.consultar("x", k=5, desde="2026-06-01")[0].id == cambiado[0].metadata["id"]


def test_dos_indices_en_memoria_no_se_pisan(emb):
    a, b = IndiceVectorial(emb, ruta=None), IndiceVectorial(emb, ruta=None)
    a.indexar(corpus())
    assert b.contar() == 0
    b.indexar(corpus()[:1])
    assert (a.contar(), b.contar()) == (4, 1)


def test_eliminar_purga_un_desarrollador_y_exige_filtro(indice):
    indice.indexar(corpus())
    assert indice.eliminar(desarrollador="Beto") == 2
    assert indice.contar() == 2
    assert indice.eliminar(repositorio="no/existe") == 0
    with pytest.raises(ValueError):
        indice.eliminar()


def test_fallo_del_embedder_no_pierde_los_chunks_previos(indice, emb):
    indice.indexar(corpus())
    cambiado = corpus()
    cambiado[0].page_content = "texto distinto"

    def falla(textos):
        raise RuntimeError("embedder caido")

    emb.embed_documents = falla
    with pytest.raises(RuntimeError):
        indice.indexar(cambiado[:1])
    assert indice.contar() == 4


def test_chunk_sin_metadatos_obligatorios_y_login_en_mayusculas(indice):
    with pytest.raises(ValueError):
        indice.indexar([Document(page_content="x", metadata={"id": "a"})])
    indice.indexar(segmentar([doc("Ana", "org/api", "commits", "texto")]))
    assert indice.consultar("texto", desarrollador="ana")


def test_fechas_imposibles_se_rechazan(indice):
    indice.indexar(corpus())
    for mala in ("2026-13-45", "2026-3-5"):
        with pytest.raises(ValueError):
            indice.consultar("x", desde=mala)


def test_orden_por_similitud_dentro_del_filtro_y_k_mayor_que_resultados(indice):
    indice.indexar(corpus())
    res = indice.consultar("parser de configuracion", k=50, desde="2026-01-01")
    assert len(res) == 4
    assert res[0].id == "ana|org/api|commits|0"
    assert [r.distancia for r in res] == sorted(r.distancia for r in res)
    identico = indice.consultar("corrige bug en el parser de configuracion", k=1)[0]
    assert identico.distancia == pytest.approx(0.0, abs=1e-6)


def test_documento_sin_una_de_las_fechas(indice):
    d = doc("ana", "org/api", "issues", "abrio el issue 3", desde="", hasta="2026-05-01")
    indice.indexar(segmentar([d]))
    assert indice.consultar("issue", hasta="2026-06-01") == []
    assert len(indice.consultar("issue", desde="2026-04-01")) == 1
