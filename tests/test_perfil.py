import copy
import json

import pytest

from devmetrics.arquetipos import (
    DATOS_INSUFICIENTES,
    DOMINANTE,
    MIXTO,
    Actividad,
    Commit,
    Senales,
    calcular_perfil,
    calcular_senales,
    cargar,
    desde_dict,
)
from devmetrics.arquetipos.configuracion import CLASES

CONFIG = cargar()


def _commits(n, mensaje, archivo, repo="r"):
    return tuple(Commit(mensaje, (archivo,), repo=repo) for _ in range(n))


def test_sin_actividad_reparto_uniforme_y_sin_clase():
    p = calcular_perfil(calcular_senales(Actividad(), CONFIG), CONFIG)
    assert p.estado == DATOS_INSUFICIENTES
    assert p.dominante is None
    assert p.tendencia is None
    assert p.confianza == "baja"
    assert p.eventos_faltantes == CONFIG.minimo_eventos
    for v in p.puntajes.values():
        assert v == pytest.approx(1 / 3)


def test_poca_actividad_no_declara_clase_pero_muestra_tendencia():
    actividad = Actividad(commits=_commits(CONFIG.minimo_eventos - 1, "update", "k8s/a.yaml"))
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.estado == DATOS_INSUFICIENTES
    assert p.dominante is None
    assert p.tendencia == "druid"
    assert p.eventos_faltantes == 1


def test_volumen_exacto_en_el_minimo_ya_puede_clasificar():
    actividad = Actividad(commits=_commits(CONFIG.minimo_eventos, "update", "k8s/a.yaml"))
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.estado == DOMINANTE
    assert p.dominante == "druid"
    assert p.confianza == "baja"
    assert p.eventos_faltantes == 0


def test_una_sola_clase_dominante_con_confianza_alta():
    actividad = Actividad(
        commits=_commits(40, "chart", "k8s/a.yaml", "r1")
        + _commits(70, "x", "terraform/a.tf", "r2")
    )
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.estado == DOMINANTE
    assert p.dominante == "druid"
    assert p.confianza == "alta"
    assert p.puntajes["druid"] > 0.9


def test_confianza_alta_no_se_da_con_repositorio_desconocido():
    s = Senales(n_commits=150, f_infraestructura=0.9, repos=0)
    assert calcular_perfil(s, CONFIG).confianza == "media"


def test_confianza_alta_exige_mas_de_un_repositorio():
    actividad = Actividad(commits=_commits(120, "chart", "k8s/a.yaml", "r1"))
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.confianza == "media"


def test_empate_exacto_es_mixto_sin_tendencia():
    actividad = Actividad(
        commits=_commits(10, "chart", "k8s/a.yaml") + _commits(10, "guide", "docs/a.md")
    )
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.estado == MIXTO
    assert p.dominante is None
    assert p.tendencia is None
    assert p.margen == pytest.approx(0.0)


def test_mezcla_con_margen_insuficiente_es_mixto_con_tendencia():
    actividad = Actividad(
        commits=_commits(11, "chart", "k8s/a.yaml") + _commits(9, "guide", "docs/a.md")
    )
    p = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert p.estado == MIXTO
    assert p.dominante is None
    assert p.tendencia == "druid"
    assert p.margen == pytest.approx(0.1)


def test_margen_exactamente_igual_al_umbral_es_dominante():
    s = Senales(n_commits=20, f_infraestructura=0.6, f_documentacion=0.4)
    p = calcular_perfil(s, CONFIG)
    assert p.margen == pytest.approx(CONFIG.margen_minimo)
    assert p.estado == DOMINANTE
    assert p.dominante == "druid"


def test_margen_justo_bajo_el_umbral_es_mixto():
    s = Senales(n_commits=20, f_infraestructura=0.59, f_documentacion=0.41)
    p = calcular_perfil(s, CONFIG)
    assert p.estado == MIXTO


def test_evidencia_baja_no_fuerza_clase():
    s = Senales(n_commits=40, f_documentacion=0.2, f_codigo=0.8)
    p = calcular_perfil(s, CONFIG)
    assert p.evidencia < CONFIG.evidencia_minima
    assert p.estado == MIXTO
    assert p.dominante is None


@pytest.mark.parametrize(
    "senales",
    [
        Senales(),
        Senales(n_commits=30, f_infraestructura=0.5, f_documentacion=0.2, f_correccion=0.3),
        Senales(n_commits=5, revisiones=200, comentarios=40, issues_atendidos=9),
    ],
)
def test_los_puntajes_suman_uno(senales):
    p = calcular_perfil(senales, CONFIG)
    assert set(p.puntajes) == set(CLASES)
    assert sum(p.puntajes.values()) == pytest.approx(1.0)
    assert all(0.0 <= v <= 1.0 for v in p.puntajes.values())


def test_revisiones_y_correcciones_orientan_a_cleric():
    s = Senales(n_commits=30, f_correccion=0.5, f_codigo=1.0, revisiones=400, issues_atendidos=10)
    p = calcular_perfil(s, CONFIG)
    assert p.dominante == "cleric"


def test_comentarios_ajenos_orientan_a_bard():
    s = Senales(n_commits=3, comentarios=60, f_documentacion=0.5, f_codigo=0.5)
    p = calcular_perfil(s, CONFIG)
    assert p.tendencia == "bard"


def test_perfil_serializable_a_dict():
    p = calcular_perfil(Senales(n_commits=20, f_infraestructura=0.9), CONFIG)
    datos = json.loads(json.dumps(p.a_dict()))
    assert datos["estado"] == DOMINANTE
    assert set(datos["puntajes"]) == set(CLASES)


def _datos_defecto():
    from importlib import resources

    texto = (
        resources.files("devmetrics.arquetipos")
        .joinpath("configuracion_defecto.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(texto)


def test_cambiar_el_diccionario_de_rutas_cambia_la_mezcla_sin_tocar_codigo():
    actividad = Actividad(commits=_commits(20, "update", "notas/guia.md"))
    antes = calcular_perfil(calcular_senales(actividad, CONFIG), CONFIG)
    assert antes.dominante == "bard"

    datos = copy.deepcopy(_datos_defecto())
    datos["rutas"]["documentacion"] = []
    datos["rutas"]["infraestructura"].append("\\.md$")
    nueva = desde_dict(datos)
    despues = calcular_perfil(calcular_senales(actividad, nueva), nueva)
    assert despues.dominante == "druid"


def test_cargar_configuracion_desde_archivo(tmp_path):
    datos = _datos_defecto()
    datos["umbrales"]["minimo_eventos"] = 50
    datos["umbrales"]["confianza_media"] = 60
    datos["umbrales"]["confianza_alta"] = 200
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    config = cargar(ruta)
    actividad = Actividad(commits=_commits(20, "update", "k8s/a.yaml"))
    perfil = calcular_perfil(calcular_senales(actividad, config), config)
    assert perfil.estado == DATOS_INSUFICIENTES


def test_configuracion_invalida():
    datos = _datos_defecto()
    datos["umbrales"]["confianza_media"] = 5
    with pytest.raises(ValueError):
        desde_dict(datos)
    datos = _datos_defecto()
    del datos["pesos"]["bard"]
    with pytest.raises(ValueError):
        desde_dict(datos)
    datos = _datos_defecto()
    datos["rutas"]["inventada"] = ["x"]
    with pytest.raises(ValueError):
        desde_dict(datos)
