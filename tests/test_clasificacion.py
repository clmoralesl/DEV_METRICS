import json

from muestra_agregados import POCA_ACTIVIDAD, POSITIVOS, senales

from devmetrics.agente import clasificar, comparar_con_reglas, evidencia_de_senales
from devmetrics.agente.clasificacion import normalizar_fuentes
from devmetrics.arquetipos import Senales, calcular_perfil, cargar, desde_dict

CONFIG = cargar()
S_DRUID = senales(POSITIVOS["D1"])  # 30 commits, infraestructura 96 %


class LLMFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def invocar(self, mensajes):
        self.llamadas.append(mensajes)
        return self.respuestas[min(len(self.llamadas) - 1, len(self.respuestas) - 1)]


def salida(mezcla=(0.85, 0.05, 0.10), dominante="Druid", confianza="media", fuente="S2", **extra):
    datos = {
        "razonamiento": "La infraestructura domina los archivos tocados.",
        "mezcla": dict(zip(("Druid", "Cleric", "Bard"), mezcla)),
        "dominante": dominante,
        "confianza": confianza,
        "evidencias": [{"fuente": fuente, "descripcion": "mayoria de archivos de infraestructura"}],
        "faltante": "",
    }
    datos.update(extra)
    return json.dumps(datos)


def test_la_evidencia_se_cita_con_identificadores_estables():
    texto, fuentes = evidencia_de_senales(S_DRUID)
    assert fuentes["S1"].startswith("30 commits")
    assert any("96%" in linea for linea in fuentes.values())
    assert texto.splitlines()[0].startswith("[S1]")


def test_salida_valida_se_acepta_y_usa_razonamiento_cot():
    llm = LLMFalso(salida())
    resultado = clasificar("D1", S_DRUID, llm, CONFIG)
    assert resultado.valida and resultado.intentos == 1
    assert resultado.dominante == "Druid"
    assert resultado.razonamiento
    contenido = " ".join(m["content"] for m in llm.llamadas[0])
    assert "razonamiento" in contenido and "D1" in contenido


def test_salida_invalida_se_repite_una_vez_con_los_errores():
    llm = LLMFalso("no es json", salida())
    resultado = clasificar("D1", S_DRUID, llm, CONFIG)
    assert resultado.valida and resultado.intentos == 2
    assert "Corrige" in llm.llamadas[1][-1]["content"]


def test_dos_salidas_invalidas_se_marcan_sin_lanzar_ni_repetir_mas():
    llm = LLMFalso("no es json", "tampoco")
    resultado = clasificar("D1", S_DRUID, llm, CONFIG)
    assert not resultado.valida and resultado.intentos == 2
    assert resultado.errores and resultado.mezcla is None
    assert len(llm.llamadas) == 2


def test_cita_fuera_del_contexto_se_rechaza():
    llm = LLMFalso(salida(fuente="S99"))
    resultado = clasificar("D1", S_DRUID, llm, CONFIG)
    assert not resultado.valida
    assert any("no esta en el contexto" in e for e in resultado.errores)


def test_los_identificadores_con_corchetes_o_linea_completa_se_normalizan():
    datos = {"evidencias": [{"fuente": "[S1]"}, {"fuente": " S2 "}, {"fuente": "S3: texto"}]}
    normalizar_fuentes(datos, {"S1", "S2", "S3"})
    assert [e["fuente"] for e in datos["evidencias"]] == ["S1", "S2", "S3"]
    resultado = clasificar("D1", S_DRUID, LLMFalso(salida(fuente="[S2]")), CONFIG)
    assert resultado.valida


def test_el_margen_se_lee_de_la_configuracion():
    dato_estricto = {
        **_datos_config(),
        "umbrales": {**_datos_config()["umbrales"], "margen_minimo": 0.9},
    }
    estricta = desde_dict(dato_estricto)
    resultado = clasificar("D1", S_DRUID, LLMFalso(salida()), estricta)
    assert resultado.valida and resultado.dominante == "mixto"
    assert any("dominante derivado" in c for c in resultado.correcciones)


def _datos_config():
    from importlib import resources

    texto = (
        resources.files("devmetrics.arquetipos")
        .joinpath("configuracion_defecto.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(texto)


def test_guardia_de_poca_actividad_fuerza_mixto_y_registra_si_ya_cumplia():
    poca = senales(POCA_ACTIVIDAD["L1"])
    assert calcular_perfil(poca, CONFIG).estado == "datos_insuficientes"
    incumple = clasificar("L1", poca, LLMFalso(salida(confianza="alta")), CONFIG)
    assert incumple.guardia_aplicada and incumple.cumplia_guardia is False
    assert incumple.dominante == "mixto" and incumple.confianza == "baja"
    assert incumple.faltante
    cumple = clasificar(
        "L1",
        poca,
        LLMFalso(salida(dominante="mixto", confianza="baja", faltante="mas commits")),
        CONFIG,
    )
    assert cumple.cumplia_guardia is True and cumple.confianza == "baja"


def test_sin_datos_insuficientes_no_hay_guardia():
    resultado = clasificar("D1", S_DRUID, LLMFalso(salida()), CONFIG)
    assert not resultado.guardia_aplicada and resultado.cumplia_guardia is None


def test_registro_de_discrepancias_frente_al_modelo_de_reglas():
    perfil = calcular_perfil(S_DRUID, CONFIG)
    coincide = clasificar("D1", S_DRUID, LLMFalso(salida()), CONFIG)
    assert coincide.discrepancia["difiere_dominante"] is False
    assert coincide.discrepancia["dominante_reglas"] == "Druid"
    assert coincide.discrepancia["confianza_reglas"] == perfil.confianza
    otra = clasificar(
        "D1",
        S_DRUID,
        LLMFalso(salida(mezcla=(0.1, 0.8, 0.1), dominante="Cleric")),
        CONFIG,
    )
    assert otra.discrepancia["difiere_dominante"] is True
    assert otra.discrepancia["max_diferencia_mezcla"] > 0.5
    invalida = clasificar("D1", S_DRUID, LLMFalso("x"), CONFIG)
    assert comparar_con_reglas(invalida, perfil)["max_diferencia_mezcla"] is None


def test_sin_actividad_la_evidencia_no_queda_vacia():
    _, fuentes = evidencia_de_senales(Senales())
    assert "S1" in fuentes


def test_con_poca_actividad_la_guardia_cubre_tambien_la_salida_invalida():
    poca = senales(POCA_ACTIVIDAD["L2"])
    resultado = clasificar("L2", poca, LLMFalso("", ""), CONFIG)
    assert not resultado.valida and resultado.guardia_aplicada
    assert resultado.dominante == "mixto" and resultado.confianza == "baja"
    assert resultado.cumplia_guardia is False and resultado.faltante


def test_la_respuesta_cruda_queda_registrada_aun_si_es_invalida():
    resultado = clasificar("D1", S_DRUID, LLMFalso("no es json", "tampoco"), CONFIG)
    assert resultado.texto_crudo == "tampoco"


def test_evidencia_omite_lo_no_medido_si_se_pide():
    completa, _ = evidencia_de_senales(S_DRUID)
    medida, fuentes = evidencia_de_senales(S_DRUID, omitir_no_medidas=True)
    assert "comentarios" in completa and "issues atendidos" in completa
    assert "repositorio" in completa
    assert "comentarios" not in medida and "issues" not in medida
    assert "repositorio" not in medida
    assert fuentes["S1"] == "30 commits analizados"
    assert any("revisiones" in linea for linea in fuentes.values())


def test_clasificar_pasa_la_opcion_a_la_evidencia():
    llm = LLMFalso(salida())
    clasificar("D1", S_DRUID, llm, CONFIG, omitir_no_medidas=True)
    contenido = " ".join(m["content"] for m in llm.llamadas[0])
    assert "0 issues atendidos" not in contenido


def test_el_dominante_se_deriva_de_la_mezcla_y_no_del_llm():
    # el LLM declara Druid con una mezcla que no supera el margen: la regla da mixto
    cercana = salida(mezcla=(0.45, 0.35, 0.20), dominante="Druid")
    resultado = clasificar("D1", S_DRUID, LLMFalso(cercana), CONFIG)
    assert resultado.valida and resultado.dominante == "mixto"
    assert resultado.correcciones
    # el LLM dice mixto con un margen amplio y confianza media: la regla da la clase
    firme = salida(mezcla=(0.80, 0.10, 0.10), dominante="mixto")
    resultado = clasificar("D1", S_DRUID, LLMFalso(firme), CONFIG)
    assert resultado.dominante == "Druid" and resultado.valida


def test_la_confianza_baja_impone_mixto_aunque_el_margen_sea_amplio():
    baja = salida(mezcla=(0.80, 0.10, 0.10), dominante="Druid", confianza="baja", faltante="mas")
    resultado = clasificar("D1", S_DRUID, LLMFalso(baja), CONFIG)
    assert resultado.valida and resultado.dominante == "mixto"


def test_una_mezcla_que_no_suma_uno_se_renormaliza_y_se_registra():
    datos = json.loads(salida())
    datos["mezcla"] = {"Druid": 1.7, "Cleric": 0.1, "Bard": 0.2}
    resultado = clasificar("D1", S_DRUID, LLMFalso(json.dumps(datos)), CONFIG)
    assert resultado.valida and abs(sum(resultado.mezcla.values()) - 1) < 0.01
    assert any("renormalizada" in c for c in resultado.correcciones)
    assert resultado.dominante == "Druid"


def test_mezcla_con_valores_negativos_no_se_corrige_y_se_rechaza():
    datos = json.loads(salida())
    datos["mezcla"] = {"Druid": 1.2, "Cleric": -0.2, "Bard": 0.0}
    resultado = clasificar("D1", S_DRUID, LLMFalso(json.dumps(datos)), CONFIG)
    assert not resultado.valida
