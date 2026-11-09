import pytest

from devmetrics.prompts import (
    ErrorSalida,
    extraer_json,
    validar_arquetipo,
    validar_recomendacion,
    validar_salida,
    validar_tipo_cambio,
)

ARQUETIPO_OK = {
    "mezcla": {"Druid": 0.7, "Cleric": 0.2, "Bard": 0.1},
    "dominante": "Druid",
    "confianza": "alta",
    "evidencias": [{"fuente": "c1", "descripcion": "migraciones de base de datos"}],
    "faltante": "",
}

FUENTES = ["p1", "r1"]

RECOMENDACION_OK = {
    "evidencia_suficiente": True,
    "respuesta": "Se sugiere a dev_a.",
    "candidatos": [{"alias": "dev_a", "justificacion": "revisa PR", "fuentes": ["p1"]}],
    "fuentes": ["p1", "r1"],
    "faltante": "",
}


# extraer_json

def test_extrae_json_con_cerca_y_texto_alrededor():
    texto = 'Claro:\n```json\n{"tipo": "otro", "justificacion": "x"}\n```\nlisto'
    assert extraer_json(texto)["tipo"] == "otro"


def test_extrae_json_ignorando_bloque_think():
    texto = '<think>pienso {"a": 1}</think>{"tipo": "otro", "justificacion": "x"}'
    assert extraer_json(texto) == {"tipo": "otro", "justificacion": "x"}


def test_extrae_json_con_llaves_previas_no_validas():
    assert extraer_json('uso {x} y luego {"a": 1}') == {"a": 1}


@pytest.mark.parametrize("texto", ["", "sin json", "{incompleto", "[1, 2]"])
def test_sin_objeto_json_es_error(texto):
    with pytest.raises(ErrorSalida):
        extraer_json(texto)


# tipo_cambio

def test_tipo_cambio_valido_con_y_sin_razonamiento():
    base = {"tipo": "correccion", "justificacion": "arregla un fallo"}
    assert validar_tipo_cambio(base) == base
    assert validar_tipo_cambio({**base, "razonamiento": "paso 1"})["tipo"] == "correccion"


@pytest.mark.parametrize(
    "datos",
    [
        {"tipo": "bugfix", "justificacion": "x"},
        {"tipo": "otro"},
        {"tipo": "otro", "justificacion": "  "},
        {"tipo": "otro", "justificacion": "x", "razonamiento": ""},
        {},
    ],
)
def test_tipo_cambio_invalido(datos):
    with pytest.raises(ErrorSalida):
        validar_tipo_cambio(datos)


def test_validar_salida_integra_extraccion_y_esquema():
    texto = '```json\n{"tipo": "refactor", "justificacion": "mueve codigo"}\n```'
    assert validar_salida("tipo_cambio", texto)["tipo"] == "refactor"
    with pytest.raises(ErrorSalida):
        validar_salida("tipo_cambio", "no es json")


def test_validar_salida_rechaza_prompt_sin_salida_estructurada():
    with pytest.raises(ValueError, match="no tiene salida estructurada"):
        validar_salida("sistema", "{}")


# clasificacion_arquetipo

def test_arquetipo_valido():
    assert validar_arquetipo(ARQUETIPO_OK)["dominante"] == "Druid"


def test_arquetipo_mixto_dentro_del_margen_es_valido():
    mezcla = {"Druid": 0.4, "Cleric": 0.35, "Bard": 0.25}
    datos = {**ARQUETIPO_OK, "mezcla": mezcla, "dominante": "mixto"}
    assert validar_arquetipo(datos)["dominante"] == "mixto"


def test_arquetipo_poca_actividad_sin_clase_forzada():
    datos = {
        "mezcla": {"Druid": 0.4, "Cleric": 0.4, "Bard": 0.2},
        "dominante": "mixto",
        "confianza": "datos_insuficientes",
        "evidencias": [{"fuente": "c1", "descripcion": "un solo commit"}],
        "faltante": "revisiones de PR y mas commits",
    }
    assert validar_arquetipo(datos)["confianza"] == "datos_insuficientes"


def _con(**cambios):
    return {**ARQUETIPO_OK, **cambios}


@pytest.mark.parametrize(
    "datos, fragmento",
    [
        (_con(mezcla={"Druid": 0.5, "Cleric": 0.2, "Bard": 0.1}), "suma"),
        (_con(mezcla={"Druid": 0.7, "Cleric": 0.3}), "claves"),
        (_con(mezcla={"Druid": 1.2, "Cleric": -0.1, "Bard": -0.1}), "entre 0 y 1"),
        (_con(dominante="Mago"), "dominante invalido"),
        (_con(dominante="Cleric"), "mayor puntaje"),
        (_con(mezcla={"Druid": 0.5, "Cleric": 0.4, "Bard": 0.1}), "supera a la segunda"),
        (_con(confianza="segura"), "confianza invalida"),
        (_con(confianza="datos_insuficientes", faltante="mas commits"), "mixto"),
        (_con(confianza="baja", faltante=""), "faltante"),
        (_con(evidencias=[]), "evidencias"),
        (_con(evidencias=[{"fuente": "c1"}]), "evidencias[0]"),
    ],
)
def test_arquetipo_invalido(datos, fragmento):
    with pytest.raises(ErrorSalida) as error:
        validar_arquetipo(datos)
    assert fragmento in str(error.value)


def test_arquetipo_margen_configurable():
    datos = _con(mezcla={"Druid": 0.5, "Cleric": 0.4, "Bard": 0.1})
    assert validar_arquetipo(datos, margen_minimo=0.1)["dominante"] == "Druid"


# recomendacion

def test_recomendacion_valida():
    assert validar_recomendacion(RECOMENDACION_OK, FUENTES)["evidencia_suficiente"] is True


def test_recomendacion_con_evidencia_insuficiente_es_valida():
    datos = {
        "evidencia_suficiente": False,
        "respuesta": "No hay datos para responder.",
        "candidatos": [],
        "fuentes": [],
        "faltante": "perfiles de desarrolladores Rust",
    }
    assert validar_recomendacion(datos, FUENTES)["evidencia_suficiente"] is False


def test_recomendacion_cita_fuentes_que_no_estan_en_el_contexto():
    validar_recomendacion(RECOMENDACION_OK, fuentes_disponibles=["p1", "r1"])
    with pytest.raises(ErrorSalida, match="no estan en el contexto"):
        validar_recomendacion(RECOMENDACION_OK, fuentes_disponibles=["p1"])


def _rec(**cambios):
    return {**RECOMENDACION_OK, **cambios}


@pytest.mark.parametrize(
    "datos, fragmento",
    [
        (_rec(evidencia_suficiente="si"), "booleano"),
        (_rec(respuesta=""), "respuesta"),
        (_rec(candidatos=[]), "al menos un candidato"),
        (_rec(fuentes=[]), "al menos una fuente"),
        (_rec(candidatos=[{"alias": "a", "justificacion": "x", "fuentes": []}]), "candidatos[0]"),
        (_rec(candidatos=[{"alias": "a", "justificacion": "x", "fuentes": ["zz"]}]), "ausentes"),
        (_rec(evidencia_suficiente=False, faltante="falta"), "no debe haber candidatos"),
        (_rec(evidencia_suficiente=False, candidatos=[], faltante=""), "faltante"),
        (_rec(candidatos="dev_a"), "lista"),
    ],
)
def test_recomendacion_invalida(datos, fragmento):
    with pytest.raises(ErrorSalida) as error:
        validar_recomendacion(datos, FUENTES)
    assert fragmento in str(error.value)


# ajustes tras la revision

def test_extrae_json_de_la_segunda_cerca_y_con_think_sin_cerrar():
    texto = '```\nnota\n```\n```json\n{"a": 1}\n```'
    assert extraer_json(texto) == {"a": 1}
    assert extraer_json('{"a": 2}<think>sin cerrar {"b": 3}') == {"a": 2}


def test_arquetipo_baja_confianza_exige_mixto_pero_acepta_tendencia():
    datos = _con(confianza="baja", faltante="mas revisiones", dominante="mixto")
    datos["mezcla"] = {"Druid": 0.5, "Cleric": 0.3, "Bard": 0.2}
    assert validar_arquetipo(datos)["dominante"] == "mixto"
    with pytest.raises(ErrorSalida, match="debe ser mixto"):
        validar_arquetipo(_con(confianza="baja", faltante="mas revisiones"))


def test_arquetipo_evidencias_deben_estar_en_el_contexto():
    validar_arquetipo(ARQUETIPO_OK, fuentes_disponibles=["c1", "c2"])
    with pytest.raises(ErrorSalida, match="no esta en el contexto"):
        validar_arquetipo(ARQUETIPO_OK, fuentes_disponibles=["c9"])


def test_recomendacion_rechaza_candidatos_inventados():
    validar_recomendacion(RECOMENDACION_OK, FUENTES, aliases_disponibles=["dev_a"])
    with pytest.raises(ErrorSalida, match="candidatos que no estan"):
        validar_recomendacion(RECOMENDACION_OK, FUENTES, aliases_disponibles=["dev_z"])


def test_recomendacion_sin_fuentes_disponibles_es_error_de_uso():
    texto = (
        '{"evidencia_suficiente": false, "respuesta": "x", "candidatos": [], '
        '"fuentes": [], "faltante": "y"}'
    )
    with pytest.raises(ValueError, match="fuentes_disponibles"):
        validar_salida("recomendacion", texto)
    assert validar_salida("recomendacion", texto, fuentes_disponibles=[])["faltante"] == "y"
