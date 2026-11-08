import pytest

from devmetrics.arquetipos import Actividad, Commit, calcular_senales, cargar, clasificar_cambio
from devmetrics.arquetipos.senales import categoria_ruta

CONFIG = cargar()


@pytest.mark.parametrize(
    "ruta, esperada",
    [
        ("terraform/main.tf", "infraestructura"),
        ("deploy/k8s/app.yaml", "infraestructura"),
        ("db/migrations/001.sql", "infraestructura"),
        ("Dockerfile", "infraestructura"),
        ("README.md", "documentacion"),
        ("docs/guia.rst", "documentacion"),
        ("web/src/App.tsx", "frontend"),
        ("styles/main.css", "frontend"),
        ("tests/test_api.py", "pruebas"),
        ("src/app.test.ts", "pruebas"),
        ("src/servicio.py", "codigo"),
        ("src\\servicio.py", "codigo"),
    ],
)
def test_categoria_ruta(ruta, esperada):
    assert categoria_ruta(ruta, CONFIG) == esperada


def test_correccion_por_contenido_sin_prefijo():
    commit = Commit("Corrige el calculo del total", ("src/total.py",))
    assert clasificar_cambio(commit, CONFIG) == "correccion"


def test_fix_en_solo_documentacion_no_es_correccion():
    commit = Commit("fix typo in guide", ("docs/guia.md", "README.md"))
    assert clasificar_cambio(commit, CONFIG) == "documentacion"


def test_commit_solo_infra_toma_tipo_infraestructura():
    commit = Commit("fix cluster values", ("k8s/values.yaml",))
    assert clasificar_cambio(commit, CONFIG) == "infraestructura"


def test_fix_con_codigo_y_docs_es_correccion():
    commit = Commit("fix crash on empty input", ("src/a.py", "README.md"))
    assert clasificar_cambio(commit, CONFIG) == "correccion"


def test_palabras_de_correccion_son_palabras_completas():
    assert clasificar_cambio(Commit("add test fixture", ("src/a.py",)), CONFIG) == "funcionalidad"
    assert clasificar_cambio(Commit("fixes crash", ("src/a.py",)), CONFIG) == "correccion"
    assert clasificar_cambio(Commit("Fixed error handling", ("src/a.py",)), CONFIG) == "correccion"


def test_tipo_inyectado_reemplaza_a_la_heuristica():
    commit = Commit("fix algo", ("src/a.py",), tipo_cambio="refactor")
    assert clasificar_cambio(commit, CONFIG) == "refactor"


def test_tipo_inyectado_invalido():
    with pytest.raises(ValueError):
        clasificar_cambio(Commit("x", tipo_cambio="inventado"), CONFIG)


def test_otros_tipos_por_palabras():
    assert clasificar_cambio(Commit("refactor service layer", ("src/a.py",)), CONFIG) == "refactor"
    assert clasificar_cambio(Commit("add export option", ("src/a.py",)), CONFIG) == "funcionalidad"
    assert clasificar_cambio(Commit("wip", ("src/a.py",)), CONFIG) == "otro"


def test_senales_sin_actividad():
    s = calcular_senales(Actividad(), CONFIG)
    assert s.volumen == 0
    assert s.f_infraestructura == s.f_correccion == 0.0
    assert s.repos == 0


def test_senales_sinteticas():
    actividad = Actividad(
        commits=(
            Commit("fix bug", ("src/a.py", "tests/test_a.py"), repo="r1"),
            Commit("update chart", ("k8s/app.yaml",), repo="r2"),
            Commit("fix typo", ("README.md",), repo="r2"),
            Commit("add page", ("web/Home.tsx",), repo="r2"),
        ),
        revisiones=3,
        comentarios=2,
        issues_atendidos=1,
    )
    s = calcular_senales(actividad, CONFIG)
    assert s.n_commits == 4
    assert s.f_infraestructura == pytest.approx(1 / 5)
    assert s.f_documentacion == pytest.approx(1 / 5)
    assert s.f_frontend == pytest.approx(1 / 5)
    assert s.f_pruebas == pytest.approx(1 / 5)
    assert s.f_codigo == pytest.approx(1 / 5)
    assert s.f_correccion == pytest.approx(1 / 4)
    assert s.repos == 2
    assert s.categorias_activas == 5
    assert s.volumen == 4 + 3 + 2 + 1
