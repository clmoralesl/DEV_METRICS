"""Referencia para el issue 13: la funcion de mezcla sobre los agregados de la muestra piloto.

Los agregados entran directamente como senales: la prueba valida el puntaje y los umbrales,
no la extraccion desde commits crudos.
"""

from muestra_agregados import MIXTOS, POSITIVOS, senales

from devmetrics.arquetipos import MIXTO, calcular_perfil, cargar

CONFIG = cargar()


def test_la_tendencia_coincide_con_la_clase_etiquetada_en_los_15():
    aciertos = 0
    for fila in POSITIVOS.values():
        perfil = calcular_perfil(senales(fila), CONFIG)
        aciertos += perfil.tendencia == fila[0]
    assert aciertos == 15


def test_clase_dominante_declarada_correcta_en_al_menos_11_de_15():
    aciertos = sum(
        calcular_perfil(senales(f), CONFIG).dominante == f[0] for f in POSITIVOS.values()
    )
    assert aciertos >= 11
    assert aciertos == 13  # con margen 0.20; ver documentacion/calibracion_arquetipos.md


def test_ningun_positivo_se_clasifica_en_otra_clase():
    for fila in POSITIVOS.values():
        perfil = calcular_perfil(senales(fila), CONFIG)
        assert perfil.dominante in (None, fila[0])


def test_los_perfiles_mixtos_no_reciben_clase_dominante():
    for alias, fila in MIXTOS.items():
        perfil = calcular_perfil(senales(fila), CONFIG)
        assert perfil.estado == MIXTO, alias
