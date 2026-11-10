import pytest
from embeddings_falsos import EmbeddingsBolsa
from github_falso import SesionFalsa, error_red

from devmetrics.conocimiento import crear_indice_interno, indexar_conocimiento
from devmetrics.indexacion import IndiceVectorial
from devmetrics.ingesta import CacheLocal, ClienteGitHub, Limites, ingerir
from devmetrics.perfiles import documentos_de, segmentar
from devmetrics.recuperacion import (
    ORIGEN_EN_VIVO,
    ORIGEN_INDEXADO,
    ORIGEN_INTERNO,
    Recuperacion,
    RecuperadorCombinado,
    consultar_en_vivo,
    crear_en_vivo,
    crear_herramienta_github,
)

REPO = "acme/demo"
LIMITES = Limites(max_commits=50, max_prs=50, max_issues=50, max_comentarios=50)
EMB = EmbeddingsBolsa()


def _cliente(sesion):
    return ClienteGitHub("token-de-prueba", session=sesion, dormir=lambda s: None)


@pytest.fixture(scope="module")
def datos_demo(tmp_path_factory):
    cliente = _cliente(SesionFalsa.desde_fixture("acme_demo.json"))
    cache = CacheLocal(tmp_path_factory.mktemp("cache"))
    return ingerir([REPO], cliente, cache, limites=LIMITES).datos


@pytest.fixture
def conocimiento():
    indice = crear_indice_interno(EMB, ruta=None)
    indexar_conocimiento(indice, "conocimiento")
    return indice


@pytest.fixture
def perfiles(datos_demo):
    indice = IndiceVectorial(EMB, ruta=None)
    for login in ("dev-alfa", "dev-beta"):
        indice.indexar(segmentar(documentos_de(login, datos_demo.values())))
    return indice


class IndiceCaido:
    def consultar(self, *a, **k):
        raise ConnectionError("chroma no responde")


def test_combina_fuentes_con_cita_en_cada_fragmento(conocimiento, perfiles):
    rec = RecuperadorCombinado(conocimiento, perfiles).recuperar("migracion a la nube")
    assert {f.origen for f in rec.fragmentos} == {ORIGEN_INTERNO, ORIGEN_INDEXADO}
    assert all(f.cita for f in rec.fragmentos)
    d = [f.distancia for f in rec.fragmentos]
    assert d == sorted(d) and len(set(d)) > 1
    assert any(c.startswith("conocimiento interno:") for c in rec.fuentes)
    assert any(c.startswith(f"GitHub: {REPO}") for c in rec.fuentes)
    texto = rec.formatear()
    assert texto.count("Fuente:") == len(rec.fragmentos)


def test_filtros_de_metadatos(conocimiento, perfiles):
    rc = RecuperadorCombinado(conocimiento, perfiles)
    rec = rc.recuperar("actividad", desarrollador="DEV-ALFA", categoria="criterio", k_externa=10)
    internos = [f for f in rec.fragmentos if f.origen == ORIGEN_INTERNO]
    externos = [f for f in rec.fragmentos if f.origen == ORIGEN_INDEXADO]
    assert internos and all(f.metadatos["categoria"] == "criterio" for f in internos)
    assert externos and all(f.metadatos["desarrollador"] == "dev-alfa" for f in externos)
    solo = rc.recuperar("actividad", tipo_fuente="commits", k_interna=0, k_externa=10)
    assert solo.fragmentos and {f.metadatos["tipo_fuente"] for f in solo.fragmentos} == {"commits"}


def test_k_total_y_k_por_fuente(conocimiento, perfiles):
    rc = RecuperadorCombinado(conocimiento, perfiles, k_interna=3, k_externa=3)
    assert len(rc.recuperar("commits", k=2).fragmentos) == 2
    solo_ext = rc.recuperar("commits", k_interna=0)
    assert {f.origen for f in solo_ext.fragmentos} == {ORIGEN_INDEXADO}
    with pytest.raises(ValueError):
        rc.recuperar("commits", k=0)


def test_fecha_invalida_es_error_del_llamador(conocimiento, perfiles):
    with pytest.raises(ValueError, match="fecha invalida"):
        RecuperadorCombinado(conocimiento, perfiles).recuperar("x", desde="ayer")


def test_consulta_sin_resultados_por_umbral(conocimiento, perfiles):
    rec = RecuperadorCombinado(conocimiento, perfiles).recuperar(
        "migracion a la nube", distancia_maxima=-1.0
    )
    assert rec.sin_resultados and rec.fuentes == []
    assert rec.formatear().startswith("SIN RESULTADOS")


def test_consulta_sin_resultados_por_filtros_y_por_indices_vacios(conocimiento, perfiles):
    rec = RecuperadorCombinado(conocimiento, perfiles).recuperar(
        "x", k_interna=0, desarrollador="nadie"
    )
    assert rec.sin_resultados and rec.avisos == []
    vacio = IndiceVectorial(EMB, ruta=None)
    rec = RecuperadorCombinado(crear_indice_interno(EMB, ruta=None), vacio).recuperar("x")
    assert rec.sin_resultados
    assert "sin coincidencias" in rec.formatear()


def test_fuente_externa_caida_no_impide_responder_con_la_interna(conocimiento):
    rec = RecuperadorCombinado(conocimiento, IndiceCaido()).recuperar("migracion a la nube")
    assert rec.fragmentos and {f.origen for f in rec.fragmentos} == {ORIGEN_INTERNO}
    assert len(rec.avisos) == 1 and "fuente externa no disponible" in rec.avisos[0]
    assert "AVISOS" in rec.formatear()


def test_todas_las_fuentes_caidas(perfiles):
    rec = RecuperadorCombinado(IndiceCaido(), IndiceCaido()).recuperar("x")
    assert rec.sin_resultados and len(rec.avisos) == 2
    assert "fuente interna no disponible" in rec.formatear()


def _recuperador_vivo(conocimiento, perfiles, tmp_path, llamadas=None):
    sesion = SesionFalsa.desde_fixture("acme_demo.json")
    real = crear_en_vivo([REPO], _cliente(sesion), EMB, cache=CacheLocal(tmp_path))

    def en_vivo(consulta, dev, k, **filtros):
        if llamadas is not None:
            llamadas.append((dev, filtros))
        return real(consulta, dev, k, **filtros)

    return RecuperadorCombinado(conocimiento, perfiles, en_vivo=en_vivo)


def test_en_vivo_solo_si_el_desarrollador_no_esta_indexado(conocimiento, perfiles, tmp_path):
    llamadas = []
    rc = _recuperador_vivo(conocimiento, perfiles, tmp_path, llamadas)
    rc.recuperar("commits", desarrollador="dev-alfa")
    assert llamadas == []
    rec = rc.recuperar("commits", desarrollador="dev-gamma")
    assert [d for d, _ in llamadas] == ["dev-gamma"]
    assert ORIGEN_EN_VIVO in {f.origen for f in rec.fragmentos}
    assert any("[consulta en vivo]" in c for c in rec.fuentes)
    assert "Fuente: GitHub:" in rec.formatear()


def test_indexado_con_filtros_sin_coincidencias_no_llama_a_github(conocimiento, perfiles, tmp_path):
    llamadas = []
    rc = _recuperador_vivo(conocimiento, perfiles, tmp_path, llamadas)
    rec = rc.recuperar("commits", desarrollador="dev-alfa", desde="2001-01-01", hasta="2001-01-02")
    assert llamadas == [] and not [f for f in rec.fragmentos if f.origen != ORIGEN_INTERNO]


def test_filtros_se_propagan_a_la_consulta_en_vivo(conocimiento, perfiles, tmp_path):
    llamadas = []
    rc = _recuperador_vivo(conocimiento, perfiles, tmp_path, llamadas)
    rec = rc.recuperar("actividad", desarrollador="dev-gamma", tipo_fuente="issues", k_interna=0)
    assert llamadas[0][1]["tipo_fuente"] == "issues"
    vivos = [f for f in rec.fragmentos if f.origen == ORIGEN_EN_VIVO]
    assert vivos and {f.metadatos["tipo_fuente"] for f in vivos} == {"issues"}
    otro = rc.recuperar("a", desarrollador="dev-gamma", tipo_fuente="commits", k_interna=0)
    assert otro.sin_resultados
    fuera = rc.recuperar("actividad", desarrollador="dev-gamma", hasta="2001-01-01", k_interna=0)
    assert fuera.sin_resultados


def test_fallo_de_la_fuente_en_vivo_queda_como_aviso(conocimiento, perfiles):
    def en_vivo(*a, **k):
        raise ValueError("repo no valido")

    rc = RecuperadorCombinado(conocimiento, perfiles, en_vivo=en_vivo)
    rec = rc.recuperar("commits", desarrollador="dev-gamma", k_interna=0)
    assert rec.sin_resultados
    assert "GitHub en vivo no disponible" in rec.avisos[0]


def test_avisos_largos_se_acotan(conocimiento):
    class Caido:
        def consultar(self, *a, **k):
            raise ConnectionError("https://api.github.com/" + "x" * 500)

    rec = RecuperadorCombinado(conocimiento, Caido()).recuperar("x")
    assert len(rec.avisos[0]) < 200


def test_k_mayor_que_los_disponibles_y_umbral_parcial(conocimiento, perfiles):
    rc = RecuperadorCombinado(conocimiento, perfiles)
    todo = rc.recuperar("commits", k_interna=100, k_externa=100)
    assert 0 < len(todo.fragmentos) < 200
    distancias = sorted({f.distancia for f in todo.fragmentos})
    assert len(distancias) > 1
    corte = distancias[0]
    parcial = rc.recuperar("commits", k_interna=100, k_externa=100, distancia_maxima=corte)
    assert 0 < len(parcial.fragmentos) < len(todo.fragmentos)
    assert all(f.distancia <= corte for f in parcial.fragmentos)


def test_en_vivo_con_github_caido_se_informa(tmp_path):
    sesion = SesionFalsa({f"/repos/{REPO}/pulls": error_red()})
    cliente = ClienteGitHub("t", session=sesion, dormir=lambda s: None, max_reintentos=1)
    rec = consultar_en_vivo("commits", "dev-alfa", [REPO], cliente, EMB, cache=CacheLocal(tmp_path))
    assert rec.sin_resultados
    assert any(REPO in a for a in rec.avisos)


def test_en_vivo_un_repo_caido_no_bloquea_a_los_demas(tmp_path):
    rutas = SesionFalsa.desde_fixture("acme_demo.json").rutas
    cliente = _cliente(SesionFalsa(rutas))
    rec = consultar_en_vivo(
        "commits", "dev-alfa", ["acme/inexistente", REPO], cliente, EMB, cache=CacheLocal(tmp_path)
    )
    assert rec.fragmentos
    assert any("acme/inexistente" in a for a in rec.avisos)


def test_en_vivo_sin_actividad_o_sin_repositorios(tmp_path, datos_demo):
    assert documentos_de("dev-gamma", datos_demo.values())
    cliente = _cliente(SesionFalsa.desde_fixture("acme_demo.json"))
    rec = consultar_en_vivo("x", "persona-ajena", [REPO], cliente, EMB, cache=CacheLocal(tmp_path))
    assert rec.sin_resultados and "no tiene actividad" in rec.avisos[0]
    rec = consultar_en_vivo("x", "dev-alfa", [], cliente, EMB, cache=CacheLocal(tmp_path))
    assert rec.sin_resultados and rec.avisos


def test_herramienta_github(tmp_path):
    cliente = _cliente(SesionFalsa.desde_fixture("acme_demo.json"))
    herramienta = crear_herramienta_github(cliente, EMB, cache=CacheLocal(tmp_path))
    assert herramienta.name == "consultar_github"
    salida = herramienta.invoke(
        {"consulta": "commits", "desarrollador": "dev-alfa", "repositorios": [REPO]}
    )
    assert "Fuente: GitHub:" in salida and "[consulta en vivo]" in salida


def test_herramienta_github_no_propaga_errores(tmp_path):
    cliente = _cliente(SesionFalsa({}))
    herramienta = crear_herramienta_github(cliente, EMB, cache=CacheLocal(tmp_path))
    salida = herramienta.invoke(
        {"consulta": "x", "desarrollador": "dev-alfa", "repositorios": [REPO]}
    )
    assert salida.startswith("SIN RESULTADOS")
    for repos in (["no valido"], []):
        salida = herramienta.invoke(
            {"consulta": "x", "desarrollador": "dev-alfa", "repositorios": repos}
        )
        assert salida.startswith("SIN RESULTADOS")


def test_recuperacion_vacia_por_defecto():
    assert Recuperacion().sin_resultados
