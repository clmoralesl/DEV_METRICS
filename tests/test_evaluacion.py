import importlib.util
import json
from pathlib import Path

import pytest
from embeddings_falsos import EmbeddingsBolsa
from muestra_agregados import MIXTOS, POCA_ACTIVIDAD, POSITIVOS

from devmetrics.evaluacion import (
    CacheLLM,
    LLMConCache,
    answer_relevancy,
    clave_de_fuente,
    coincide_perfil,
    context_precision,
    context_recall,
    es_abstencion,
    extraer_json,
    faithfulness,
    similitud_coseno,
)
from devmetrics.recuperacion import Fragmento

RAIZ = Path(__file__).resolve().parents[1]
CASOS = json.loads((RAIZ / "tests" / "casos_agente.json").read_text(encoding="utf-8"))["casos"]


def _script():
    spec = importlib.util.spec_from_file_location(
        "evaluar_agente", RAIZ / "scripts" / "evaluar_agente.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


EV = _script()


def frag(documento=None, dev=None):
    meta = {"documento": documento} if documento else {"desarrollador": dev}
    return Fragmento("texto", "cita", "interna", 0.1, meta)


class LLMFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def invocar(self, mensajes):
        self.pedidos.append(mensajes)
        return self.respuestas.pop(0)


class Emb:
    def embed_query(self, texto):
        return [1.0, 0.0] if "uno" in texto else [0.0, 1.0]


def test_clave_de_fuente_distingue_interna_y_perfil():
    assert clave_de_fuente(frag(documento="req-x")) == "req-x"
    assert clave_de_fuente(frag(dev="Dev_01")) == "dev:dev_01"


def test_precision_premia_el_orden():
    primero = [frag("a"), frag("b")]
    segundo = [frag("b"), frag("a")]
    assert context_precision(primero, ["a"]) == 1.0
    assert context_precision(segundo, ["a"]) == 0.5
    assert context_precision([frag("b")], ["a"]) == 0.0
    assert context_precision([], ["a"]) == 0.0


def test_recall_y_casos_sin_referencia():
    assert context_recall([frag("a")], ["a", "b"]) == 0.5
    assert context_recall([frag("a"), frag(dev="x")], ["a", "dev:x"]) == 1.0
    assert context_precision([frag("a")], []) is None
    assert context_recall([frag("a")], []) is None


def test_extraer_json_tolera_cercos_y_texto():
    assert extraer_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extraer_json('Resultado: {"a": 1} fin') == {"a": 1}
    assert extraer_json("sin json") is None
    assert extraer_json("{roto") is None
    assert extraer_json("[1]") is None


def test_faithfulness_es_la_fraccion_respaldada():
    llm = LLMFalso(
        '{"afirmaciones": [{"texto": "a", "respaldada": true}, {"texto": "b", "respaldada": false},'
        ' {"texto": "c", "respaldada": true}, {"texto": "d", "respaldada": true}]}'
    )
    assert faithfulness(llm, "contexto", "respuesta") == 0.75
    assert "contexto" in llm.pedidos[0][0]["content"]


@pytest.mark.parametrize("salida", ["no es json", '{"afirmaciones": []}', '{"otra": 1}'])
def test_faithfulness_sin_salida_valida_es_none(salida):
    assert faithfulness(LLMFalso(salida), "c", "r") is None


def test_answer_relevancy_promedia_la_similitud():
    llm = LLMFalso('{"preguntas": ["uno", "dos"]}')
    assert answer_relevancy(llm, Emb(), "uno", "respuesta") == pytest.approx(0.5)
    assert answer_relevancy(LLMFalso("x"), Emb(), "uno", "r") is None
    assert similitud_coseno([1, 0], [1, 0]) == 1.0
    assert similitud_coseno([0, 0], [1, 0]) == 0.0


def test_abstencion_y_perfil():
    assert es_abstencion("**Evidencia insuficiente**: faltan datos")
    assert es_abstencion("Confianza baja por poca actividad")
    assert not es_abstencion("Perfil Druid con confianza alta")
    assert coincide_perfil("Es un Druid con rasgos de Cleric", "druid") is True
    assert coincide_perfil("Cleric dominante, algo de Druid", "druid") is False
    assert coincide_perfil("Es un Bard", "druid") is False
    assert coincide_perfil("Perfil mixto", "mixto") is True
    assert coincide_perfil("Confianza baja", "insuficiente") is True
    assert coincide_perfil("Es un Druid", "insuficiente") is False
    assert coincide_perfil("lo que sea", None) is None


def test_cache_evita_llamadas_repetidas_y_persiste(tmp_path):
    ruta = tmp_path / "c.json"
    llm = LLMFalso("uno", "dos")
    pausas = []
    envuelto = LLMConCache(llm, CacheLLM(ruta), "m", pausa=2.0, dormir=pausas.append)
    m1, m2 = [{"role": "user", "content": "a"}], [{"role": "user", "content": "b"}]
    assert envuelto.invocar(m1) == "uno"
    assert envuelto.invocar(m1) == "uno"
    assert envuelto.invocar(m2) == "dos"
    assert (envuelto.llamadas_reales, envuelto.aciertos_de_cache, pausas) == (2, 1, [2.0])
    nuevo = LLMConCache(LLMFalso(), CacheLLM(ruta), "m")
    assert nuevo.invocar(m2) == "dos"
    distinto = LLMConCache(LLMFalso("otro"), CacheLLM(ruta), "otro-modelo")
    assert distinto.invocar(m2) == "otro"


def test_cache_corrupta_se_ignora(tmp_path):
    ruta = tmp_path / "c.json"
    ruta.write_text("{roto", encoding="utf-8")
    assert len(CacheLLM(ruta)) == 0


def test_error_del_llm_se_propaga_sin_guardar(tmp_path):
    class Falla:
        def invocar(self, mensajes):
            raise RuntimeError("cuota")

    cache = CacheLLM(tmp_path / "c.json")
    with pytest.raises(RuntimeError):
        LLMConCache(Falla(), cache, "m").invocar([{"role": "user", "content": "x"}])
    assert len(cache) == 0


# --- conjunto de casos ---


def test_conjunto_tiene_entre_20_y_30_casos_con_ids_unicos():
    assert 20 <= len(CASOS) <= 30
    ids = [c["id"] for c in CASOS]
    assert len(set(ids)) == len(ids)
    assert {"id", "grupo", "pregunta", "perfil_esperado", "fuentes_esperadas"} <= set(CASOS[0])


def test_hay_casos_de_poca_actividad_con_abstencion_esperada():
    poca = [c for c in CASOS if c["grupo"] == "poca_actividad"]
    assert len(poca) >= 4
    assert all(c["perfil_esperado"] == "insuficiente" for c in poca)


def test_perfil_esperado_coincide_con_la_muestra():
    neutro = EV.alias_neutros()
    etiqueta = {
        neutro[a]: fila[0]
        for tabla in (POSITIVOS, MIXTOS, POCA_ACTIVIDAD)
        for a, fila in tabla.items()
    }
    poca = {neutro[a] for a in POCA_ACTIVIDAD}
    for c in CASOS:
        dev = c.get("desarrollador")
        if dev is None or dev == "dev_99":
            continue
        assert dev in etiqueta, c["id"]
        esperado = "insuficiente" if dev in poca else etiqueta[dev]
        assert c["perfil_esperado"] == esperado, c["id"]


def test_fuentes_esperadas_existen_en_el_corpus():
    corpus = EV.documentos_perfil()
    devs = {f"dev:{d.metadata['desarrollador']}" for d in corpus}
    internos = {p.stem for p in (RAIZ / "conocimiento").glob("*.md")}
    docs = {
        d.split("documento:")[1].split("\n")[0].strip()
        for p in (RAIZ / "conocimiento").glob("*.md")
        for d in [p.read_text(encoding="utf-8")]
    }
    assert internos  # hay base de conocimiento
    for c in CASOS:
        for f in c["fuentes_esperadas"]:
            assert f in devs | docs, (c["id"], f)


def test_alias_neutros_no_delatan_la_clase():
    neutro = EV.alias_neutros()
    assert len(set(neutro.values())) == len(neutro) == 23
    assert all(v.startswith("dev_") for v in neutro.values())


# --- corrida con recuperador real (embeddings falsos) y LLM falso ---


@pytest.fixture(scope="module")
def recuperador():
    return EV.construir_recuperador(EmbeddingsBolsa())


def test_evaluar_caso_solo_recuperacion(recuperador):
    r = EV.evaluar_caso(CASOS[0], recuperador, None, None)
    assert r["fuentes_recuperadas"]
    assert r["context_precision"] is not None and r["faithfulness"] is None
    assert r["abstiene"] is None and r["respuesta"] == ""


def test_evaluar_caso_con_juez_y_abstencion(recuperador):
    caso = {
        "id": "T1",
        "grupo": "poca_actividad",
        "pregunta": "uno",
        "perfil_esperado": "insuficiente",
        "fuentes_esperadas": [],
    }
    llm = LLMFalso("Evidencia insuficiente: pocos eventos.")
    r = EV.evaluar_caso(caso, recuperador, llm, Emb())
    assert r["abstiene"] is True and r["perfil_correcto"] is True
    assert r["faithfulness"] is None and len(llm.pedidos) == 1  # sin juez al abstenerse


def test_evaluar_caso_juzga_respuestas_con_evidencia(recuperador):
    caso = dict(CASOS[0])
    llm = LLMFalso(
        "dev_10 es Druid con confianza alta [1].",
        '{"afirmaciones": [{"texto": "a", "respaldada": true}]}',
        '{"preguntas": ["uno"]}',
    )
    r = EV.evaluar_caso(caso, recuperador, llm, Emb())
    assert r["perfil_correcto"] is True
    assert r["faithfulness"] == 1.0 and r["answer_relevancy"] is not None


def test_tabla_y_actualizacion_de_pruebas(tmp_path, recuperador):
    resultados = [EV.evaluar_caso(CASOS[0], recuperador, None, None)]
    tabla = EV.tabla_markdown(resultados, {"fecha": "2026-01-01", "modelo": "m"})
    assert "| Q01 |" in tabla and "**Media**" in tabla
    pruebas = tmp_path / "pruebas.md"
    pruebas.write_text("# Evidencia\n\ntexto previo\n", encoding="utf-8")
    EV.actualizar_pruebas(pruebas, tabla)
    EV.actualizar_pruebas(pruebas, tabla.replace("Q01", "QXX"))  # segunda vez: reemplaza
    texto = pruebas.read_text(encoding="utf-8")
    assert texto.count(EV.INICIO) == 1 and "QXX" in texto and "| Q01 |" not in texto
    assert texto.startswith("# Evidencia") and EV.ENCABEZADO in texto


def test_precision_no_cuenta_dos_veces_la_misma_fuente():
    assert context_precision([frag("a"), frag("a"), frag("b")], ["a"]) == 1.0
    assert context_precision([frag("b"), frag("a"), frag("a")], ["a"]) == 0.5


def test_cache_se_escribe_sin_dejar_temporales(tmp_path):
    cache = CacheLLM(tmp_path / "c.json")
    cache.guardar("k", "v")
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]
