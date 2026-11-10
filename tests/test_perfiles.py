import pytest
from langchain_core.documents import Document

from devmetrics.ingesta import actividad_de
from devmetrics.ingesta.esquema import (
    Archivo,
    Commit,
    DatosRepo,
    Issue,
    Limites,
    PullRequest,
    Revision,
)
from devmetrics.perfiles import CONFIG_CHUNKING, ConfigChunking, documentos_de, segmentar

LIMITES = Limites(10, 10, 10, 10)


def _datos(n_commits: int = 3) -> DatosRepo:
    commits = tuple(
        Commit(
            f"{i:040x}",
            "acme/demo",
            "Ana" if i % 2 == 0 else "Beto",
            f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}T10:00:00Z",
            f"corrige el error {i}\n\ncuerpo largo que no se incluye",
            (Archivo("src/a.py"), Archivo("docs/b.md")),
        )
        for i in range(n_commits)
    )
    return DatosRepo(
        "acme/demo",
        "2025-02-01",
        LIMITES,
        commits=commits,
        pull_requests=(PullRequest(1, "acme/demo", "ana", "Agrega x", "merged", "2025-01-03"),),
        revisiones=(
            Revision("acme/demo", 2, "beto", "ANA", "APPROVED", "2025-01-04"),
            Revision("acme/demo", 1, "ana", "ana", "COMMENTED", "2025-01-05"),
        ),
        issues=(
            Issue(3, "acme/demo", "beto", "Falla y", "open", "2025-01-06", ("ana",)),
            Issue(4, "acme/demo", "ana", "Duda z", "closed", "2025-01-07"),
        ),
    )


def test_un_documento_por_tipo_de_fuente_con_eventos():
    docs = documentos_de("ana", [_datos()])
    assert {d.metadata["tipo_fuente"] for d in docs} == {
        "commits",
        "pull_requests",
        "revisiones",
        "issues",
    }


def test_metadatos_escalares_y_login_sin_mayusculas():
    doc = next(
        d for d in documentos_de("ANA", [_datos(5)]) if d.metadata["tipo_fuente"] == "commits"
    )
    m = doc.metadata
    assert m["desarrollador"] == "ana"
    assert m["repositorio"] == "acme/demo"
    assert m["n_eventos"] == 3
    assert m["fecha_desde"] == "2025-01-01"
    assert m["fecha_hasta"] == "2025-01-05"
    assert all(isinstance(v, (str, int)) for v in m.values())


def test_commit_usa_solo_el_asunto_y_no_incluye_ajenos():
    texto = next(
        d for d in documentos_de("ana", [_datos()]) if d.metadata["tipo_fuente"] == "commits"
    ).page_content
    assert "corrige el error 0" in texto and "cuerpo largo" not in texto
    assert "error 1" not in texto


def test_revision_de_pr_propio_no_cuenta():
    revs = next(
        d for d in documentos_de("ana", [_datos()]) if d.metadata["tipo_fuente"] == "revisiones"
    )
    assert revs.metadata["n_eventos"] == 1


def test_issue_asignado_ajeno_y_propio_se_distinguen():
    texto = next(
        d for d in documentos_de("ana", [_datos()]) if d.metadata["tipo_fuente"] == "issues"
    ).page_content
    assert "atendio el issue #3" in texto and "abrio el issue #4" in texto


def test_sin_actividad_no_hay_documentos():
    assert documentos_de("nadie", [_datos()]) == []


def test_segmentar_conserva_metadatos_y_respeta_tamano():
    docs = documentos_de("ana", [_datos(200)])
    cfg = ConfigChunking(300, 30)
    chunks = segmentar(docs, cfg)
    assert len(chunks) > len(docs)
    assert all(len(c.page_content) <= cfg.chunk_size for c in chunks)
    primero = chunks[0].metadata
    assert primero["desarrollador"] == "ana" and primero["chunk"] == 0
    assert primero["n_chunks"] == sum(
        1 for c in chunks if c.metadata["tipo_fuente"] == primero["tipo_fuente"]
    )


def test_segmentar_no_corta_lineas_que_caben_en_un_chunk():
    docs = documentos_de("ana", [_datos(120)])
    lineas = {ln for d in docs for ln in d.page_content.splitlines()[1:]}
    chunks = segmentar(docs, ConfigChunking(300, 0))
    vistas = {ln for c in chunks for ln in c.page_content.splitlines()}
    assert lineas <= vistas


def test_segmentar_aplica_solapamiento():
    doc = Document(
        page_content=chr(10).join(f"evento numero {i:03d}" for i in range(60)),
        metadata={"desarrollador": "ana", "repositorio": "r", "tipo_fuente": "commits"},
    )
    sin = segmentar([doc], ConfigChunking(200, 0))
    con = segmentar([doc], ConfigChunking(200, 60))
    assert len(con) > len(sin)
    a, b = con[0].page_content.splitlines(), con[1].page_content.splitlines()
    assert b[0] in a and a[-1] in b


def test_chunks_tienen_id_estable_y_unico():
    chunks = segmentar(documentos_de("ana", [_datos(120)]), ConfigChunking(300, 30))
    ids = [c.metadata["id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids == [
        c.metadata["id"]
        for c in segmentar(documentos_de("ana", [_datos(120)]), ConfigChunking(300, 30))
    ]
    assert ids[0] == "ana|acme/demo|commits|0"


def test_segmentar_lista_vacia():
    assert segmentar([]) == []


def test_commit_sin_autor_no_se_atribuye():
    datos = _datos()
    sin_autor = Commit("f" * 40, "acme/demo", None, "2025-03-01T00:00:00Z", "x")
    datos = DatosRepo(datos.repo, datos.obtenido, LIMITES, commits=(sin_autor,))
    assert documentos_de("ana", [datos]) == []


def test_varios_repos_y_ninguno():
    assert documentos_de("ana", []) == []
    otro = DatosRepo("acme/otro", "2025-02-01", LIMITES, commits=_datos().commits)
    repos = {d.metadata["repositorio"] for d in documentos_de("ana", [_datos(), otro])}
    assert repos == {"acme/demo", "acme/otro"}


def test_issue_propio_y_asignado_cuenta_una_vez():
    iss = Issue(9, "acme/demo", "ana", "Mio", "open", "2025-01-08", ("ana",))
    datos = DatosRepo("acme/demo", "2025-02-01", LIMITES, issues=(iss,))
    doc = documentos_de("ana", [datos])[0]
    assert doc.metadata["n_eventos"] == 1 and "abrio el issue #9" in doc.page_content


def test_evento_sin_fecha_deja_fechas_vacias():
    rev = Revision("acme/demo", 2, "beto", "ana", "APPROVED", None)
    doc = documentos_de("ana", [DatosRepo("acme/demo", "x", LIMITES, revisiones=(rev,))])[0]
    assert doc.metadata["fecha_desde"] == "" and doc.metadata["n_eventos"] == 1


def test_paridad_con_actividad_de():
    datos = _datos()
    act = actividad_de("ana", [datos])
    docs = {
        d.metadata["tipo_fuente"]: d.metadata["n_eventos"] for d in documentos_de("ana", [datos])
    }
    assert docs["commits"] == len(act.commits)
    assert docs["revisiones"] == act.revisiones


@pytest.mark.parametrize("tam,sol", [(0, 0), (100, 100), (100, -1)])
def test_config_invalida(tam, sol):
    with pytest.raises(ValueError):
        ConfigChunking(tam, sol)


def test_config_elegida_es_la_del_experimento():
    assert (CONFIG_CHUNKING.chunk_size, CONFIG_CHUNKING.chunk_overlap) == (600, 120)
