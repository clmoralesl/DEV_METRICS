"""Casos limite y ramas de error que las pruebas por modulo no ejercitaban (issue 18).

Ninguna prueba de este archivo usa red, modelos ni claves: los servicios externos se sustituyen
por dobles (fastembed, LLM, scripts) y los indices usan carpetas temporales.
"""

import argparse
import copy
import json
import sys
import types
from importlib import resources

import pytest
from embeddings_falsos import EmbeddingsBolsa
from muestra_agregados import POSITIVOS, senales

import devmetrics.consola as consola_mod
from devmetrics.agente import Conversacion, clasificar
from devmetrics.agente.clasificacion import Clasificacion, normalizar_fuentes
from devmetrics.agente.memoria import MemoriaVentana
from devmetrics.arquetipos import cargar, desde_dict
from devmetrics.consola import Consola, LLMSimulado, indexar_perfiles, logins_de
from devmetrics.evaluacion.metricas import answer_relevancy, extraer_json
from devmetrics.ingesta import CacheLocal, DatosRepo, Limites
from devmetrics.ingesta.esquema import Archivo, Commit
from devmetrics.llm import ErrorProveedor
from devmetrics.llm.embeddings import ModeloEmbeddings
from devmetrics.recuperacion import Recuperacion


def _config_defecto() -> dict:
    texto = (
        resources.files("devmetrics.arquetipos")
        .joinpath("configuracion_defecto.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(texto)


# --- arquetipos.configuracion: validaciones --------------------------------------------------


def _con(cambio):
    datos = copy.deepcopy(_config_defecto())
    cambio(datos)
    return datos


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        (lambda d: d["pesos"]["druid"].update({"inventada": 1.0}), "senales desconocidas"),
        (lambda d: d["saturacion"].pop("issues"), "saturacion debe definir"),
        (lambda d: d["umbrales"].update({"evidencia_minima": 1.5}), "evidencia_minima"),
        (lambda d: d["umbrales"].update({"margen_minimo": 1.0}), "margen_minimo"),
        (lambda d: d["umbrales"].update({"confianza_media": 1}), "minimo_eventos <="),
        (lambda d: d["pesos"].pop("bard"), "exactamente las clases"),
        (lambda d: d["rutas"].update({"categoria_x": [r"x"]}), "categorias de ruta"),
    ],
)
def test_configuracion_invalida_se_rechaza_con_mensaje_claro(cambio, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        desde_dict(_con(cambio))


def test_la_configuracion_por_defecto_es_valida():
    assert desde_dict(_config_defecto()).margen_minimo == cargar().margen_minimo


# --- agente: memoria, consulta vacia, clasificacion -----------------------------------------


def test_memoria_ultimo_del_usuario_y_ventana_invalida():
    memoria = MemoriaVentana(ventana=2)
    assert memoria.ultimo_del_usuario() is None
    memoria.agregar("asistente", "hola")
    assert memoria.ultimo_del_usuario() is None
    memoria.agregar("usuario", "primera")
    memoria.agregar("asistente", "r1")
    memoria.agregar("asistente", "r2")  # la ventana de 2 expulsa la pregunta
    assert memoria.ultimo_del_usuario() is None
    with pytest.raises(ValueError):
        MemoriaVentana(ventana=0)
    with pytest.raises(ValueError, match="rol desconocido"):
        memoria.agregar("sistema", "x")


class _RecuperadorQueFallaSiSeUsa:
    def recuperar(self, *a, **k):
        raise AssertionError("una consulta vacia no debe recuperar")


class _LLMQueFallaSiSeUsa:
    def invocar(self, mensajes):
        raise AssertionError("una consulta vacia no debe llamar al LLM")


@pytest.mark.parametrize("consulta", ["", "   ", None])
def test_consulta_vacia_no_recupera_ni_llama_al_llm_y_emite_el_texto(consulta):
    conv = Conversacion(_RecuperadorQueFallaSiSeUsa(), _LLMQueFallaSiSeUsa())
    recibido = []
    r = conv.preguntar(consulta, en_fragmento=recibido.append)
    assert "Indica qué quieres saber" in r.texto
    assert "".join(recibido) == r.texto


class _LLMFijo:
    def __init__(self, texto):
        self.texto = texto

    def invocar(self, mensajes):
        return self.texto


def test_clasificacion_a_dict_es_serializable():
    s = senales(POSITIVOS["D1"])
    salida = json.dumps(
        {
            "razonamiento": "infra domina",
            "mezcla": {"Druid": 0.8, "Cleric": 0.1, "Bard": 0.1},
            "dominante": "Druid",
            "confianza": "media",
            "evidencias": [{"fuente": "S2", "descripcion": "infra"}],
            "faltante": "",
        }
    )
    c = clasificar("D1", s, _LLMFijo(salida), cargar())
    assert isinstance(c, Clasificacion)
    json.dumps(c.a_dict())  # no debe lanzar


def test_normalizar_fuentes_ignora_evidencias_mal_formadas():
    assert normalizar_fuentes({"evidencias": "no es lista"}, {"S1"}) == {
        "evidencias": "no es lista"
    }
    datos = {"evidencias": ["texto", {"fuente": 3}, {"fuente": "[s1]"}, {"fuente": "[S9]"}]}
    normalizar_fuentes(datos, {"S1"})
    assert datos["evidencias"][2]["fuente"] == "S1"  # conocida: se normaliza
    assert datos["evidencias"][3]["fuente"] == "[S9]"  # desconocida: se deja para el validador


def test_el_contexto_extra_se_agrega_como_fuente_citable():
    s = senales(POSITIVOS["D1"])
    mensajes = []

    class Espia:
        def invocar(self, m):
            mensajes.append(m)
            return "no es json"

    clasificar(
        "D1", s, Espia(), cargar(), contexto_extra={"R1": "requerimiento de infraestructura"}
    )
    assert "[R1] requerimiento de infraestructura" in json.dumps(mensajes[0], ensure_ascii=False)


def test_confianza_invalida_no_deriva_dominante_pero_se_rechaza():
    s = senales(POSITIVOS["D1"])
    salida = json.dumps(
        {
            "razonamiento": "x",
            "mezcla": {"Druid": 0.8, "Cleric": 0.1, "Bard": 0.1},
            "dominante": "Druid",
            "confianza": "altisima",
            "evidencias": [{"fuente": "S2", "descripcion": "infra"}],
            "faltante": "",
        }
    )
    c = clasificar("D1", s, _LLMFijo(salida), cargar())
    assert not c.valida and c.errores


# --- evaluacion.metricas: salidas del juez malformadas --------------------------------------


@pytest.mark.parametrize(
    "texto", ["", None, "sin llaves", "{ roto", "{'comillas': 'simples'}", "[1, 2]", "}{"]
)
def test_extraer_json_devuelve_none_ante_salidas_no_parseables(texto):
    assert extraer_json(texto) is None


def test_extraer_json_tolera_cercos_de_codigo():
    assert extraer_json('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize(
    "respuesta", ['{"preguntas": "no es lista"}', '{"preguntas": ["", 3, " "]}']
)
def test_relevancia_sin_preguntas_utiles_devuelve_none(respuesta):
    assert answer_relevancy(_LLMFijo(respuesta), EmbeddingsBolsa(), "pregunta", "respuesta") is None


# --- llm.embeddings: carga perezosa con doble de fastembed -----------------------------------


class _Vector:
    def __init__(self, datos):
        self._datos = datos

    def tolist(self):
        return list(self._datos)


def _fastembed_falso(monkeypatch, llamadas):
    class TextEmbedding:
        def __init__(self, model_name, cache_dir=None):
            llamadas.append((model_name, cache_dir))

        def embed(self, textos):
            return (_Vector([float(len(t)), 1.0]) for t in textos)

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=TextEmbedding)
    )


def test_embeddings_carga_el_motor_una_sola_vez(monkeypatch):
    llamadas = []
    _fastembed_falso(monkeypatch, llamadas)
    monkeypatch.setitem(sys.modules, "truststore", None)  # no instalado: debe continuar
    modelo = ModeloEmbeddings(modelo="m", cache_dir="c")
    assert llamadas == []  # el constructor no descarga nada
    assert modelo.embed_documents(["ab", "abcd"]) == [[2.0, 1.0], [4.0, 1.0]]
    assert modelo.embed_query("abc") == [3.0, 1.0]
    assert llamadas == [("m", "c")]


def test_embeddings_inyecta_el_almacen_del_sistema_si_truststore_esta_disponible(monkeypatch):
    inyectado = []
    monkeypatch.setitem(
        sys.modules,
        "truststore",
        types.SimpleNamespace(inject_into_ssl=lambda: inyectado.append(1)),
    )
    _fastembed_falso(monkeypatch, [])
    ModeloEmbeddings().embed_query("x")
    assert inyectado == [1]


# --- consola: ramas de error y utilidades ----------------------------------------------------


class _Conv:
    """Conversacion falsa que lanza la excepcion indicada al preguntar."""

    def __init__(self, error=None):
        self.error = error
        self.reiniciada = False

    def preguntar(self, texto, en_fragmento=None, **filtros):
        if self.error:
            raise self.error
        return types.SimpleNamespace(fuentes=[])

    def reiniciar(self):
        self.reiniciada = True


def _consola(error=None, **kw):
    import io

    salida = io.StringIO()
    return Consola(_Conv(error), entrada=lambda _: "", salida=salida, **kw), salida


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (ErrorProveedor("caida"), "Error del modelo: caida"),
        (ValueError("k"), "Consulta no valida: k"),
        (KeyboardInterrupt(), "Respuesta interrumpida."),
        (RuntimeError("disco"), "Error al consultar las fuentes: RuntimeError: disco"),
    ],
)
def test_preguntar_traduce_cada_error_en_un_mensaje_y_no_cierra_la_consola(error, esperado):
    c, salida = _consola(error)
    assert c.preguntar("hola") is None
    assert esperado in salida.getvalue()


def test_comando_mal_formado_no_lanza():
    c, salida = _consola()
    assert c.comando('/desarrollador "sin cerrar') is False
    assert "Comando mal formado" in salida.getvalue()


@pytest.mark.parametrize("alias", ["/salir", "/exit", "/q", "/SALIR"])
def test_los_alias_de_salida_terminan(alias):
    c, _ = _consola()
    assert c.comando(alias) is True


def test_indexar_sin_accion_configurada_o_destino_invalido_muestra_el_uso():
    c, salida = _consola()
    c.comando("/indexar")  # perfiles sin accion inyectada
    c.comando("/indexar otra")
    assert salida.getvalue().count("Uso: /indexar") == 2


def test_indexar_ejecuta_la_accion_y_muestra_su_resumen():
    c, salida = _consola(indexado_conocimiento=lambda: "listo")
    c.comando("/indexar conocimiento")
    assert "listo" in salida.getvalue()


@pytest.mark.parametrize(
    ("falla", "esperado"),
    [
        (SystemExit(2), "La orden termino con error."),
        (SystemExit(0), ""),
        (SystemExit(None), ""),
        (OSError("sin disco"), "Error: OSError: sin disco"),
    ],
)
def test_las_tareas_de_ingesta_no_cierran_la_consola(falla, esperado):
    def ingesta(args):
        raise falla

    c, salida = _consola(ingesta=ingesta)
    assert c.comando("/ingestar a/b") is False
    texto = salida.getvalue()
    assert esperado in texto
    if not esperado:
        assert texto == ""


def test_el_simulado_sin_fragmentos_declara_evidencia_insuficiente():
    llm = LLMSimulado()
    texto = llm.invocar([{"role": "user", "content": "(sin contexto)"}])
    assert texto.startswith("Evidencia insuficiente")
    assert "".join(llm.flujo([{"role": "user", "content": "x"}])).startswith("Evidencia")


def test_logins_de_reune_autores_revisores_y_asignados_sin_duplicar_ni_nulos():
    datos = types.SimpleNamespace(
        commits=[types.SimpleNamespace(autor="Ana"), types.SimpleNamespace(autor=None)],
        pull_requests=[types.SimpleNamespace(autor="ANA")],
        revisiones=[types.SimpleNamespace(revisor="beto")],
        issues=[types.SimpleNamespace(autor="Caro", asignados=("Dani", "beto"))],
    )
    assert logins_de(datos) == {"ana", "beto", "caro", "dani"}


def test_indexar_perfiles_sin_datos_devuelve_none(tmp_path):
    from devmetrics.indexacion import IndiceVectorial

    indice = IndiceVectorial(EmbeddingsBolsa(), ruta=None)
    assert indexar_perfiles(indice, str(tmp_path)) is None
    assert consola_mod._resumen_perfiles(indice, str(tmp_path)).startswith("No hay datos en")


def test_los_scripts_se_cargan_desde_su_ruta_y_las_ordenes_delegan(monkeypatch):
    modulo = consola_mod._cargar_script("ingestar")
    assert callable(modulo.main)

    llamadas = []
    falso = types.SimpleNamespace(main=lambda argv: llamadas.append(argv) or 7)
    monkeypatch.setattr(consola_mod, "_cargar_script", lambda nombre: falso)
    assert consola_mod.ingestar(["a/b"]) == 7
    assert consola_mod.indexar_conocimiento(["--indice", "x"]) == 0  # el script no devuelve codigo
    assert llamadas == [["a/b"], ["--indice", "x"]]
    assert consola_mod._resumen_conocimiento("x") == "Base de conocimiento indexada."


def _args(tmp_path, **kw):
    base = dict(
        indice=str(tmp_path / "indice"),
        data_dir=str(tmp_path / "data"),
        simulado=True,
        tecnica="zero_shot",
        repos=None,
        pregunta=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_construir_ensambla_la_consola_simulada_sin_red(tmp_path, monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    c = consola_mod.construir(_args(tmp_path))
    assert isinstance(c, Consola)
    assert c.comando("/indexar perfiles") is False  # sin datos descargados: no falla


def test_construir_con_repos_prepara_la_consulta_en_vivo_sin_llamar_a_github(tmp_path, monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    c = consola_mod.construir(_args(tmp_path, repos=["o/r"]))
    assert isinstance(c, Consola)


class _ConsolaFalsa:
    def __init__(self, respuesta):
        self._respuesta = respuesta
        self.preguntas = []

    def preguntar(self, texto):
        self.preguntas.append(texto)
        return self._respuesta

    def ejecutar(self):
        return 5


@pytest.mark.parametrize(("respuesta", "codigo"), [(object(), 0), (None, 1)])
def test_main_con_pregunta_devuelve_el_codigo_segun_la_respuesta(monkeypatch, respuesta, codigo):
    falsa = _ConsolaFalsa(respuesta)
    monkeypatch.setattr(consola_mod, "construir", lambda args: falsa)
    assert consola_mod.main(["--simulado", "--pregunta", "hola"]) == codigo
    assert falsa.preguntas == ["hola"]


def test_main_sin_orden_abre_el_chat_interactivo(monkeypatch):
    monkeypatch.setattr(consola_mod, "construir", lambda args: _ConsolaFalsa(None))
    assert consola_mod.main(["--simulado"]) == 5


def test_main_delega_ingestar_e_indexar(monkeypatch, tmp_path):
    visto = {}
    monkeypatch.setattr(consola_mod, "ingestar", lambda argv: visto.setdefault("ing", argv) and 3)
    monkeypatch.setattr(
        consola_mod, "indexar_conocimiento", lambda argv: visto.setdefault("con", argv) and 4
    )
    assert consola_mod.main(["ingestar", "o/r", "--max", "5"]) == 3
    assert visto["ing"] == ["o/r", "--max", "5"]
    assert consola_mod.main(["indexar", "conocimiento", "--indice", "ruta"]) == 4
    assert visto["con"] == ["--indice", "ruta"]


def test_main_indexar_perfiles_sin_datos_informa_y_termina_bien(tmp_path, capsys):
    codigo = consola_mod.main(
        ["indexar", "perfiles", "--indice", str(tmp_path / "i"), "--data-dir", str(tmp_path)]
    )
    assert codigo == 0
    assert "No hay datos" in capsys.readouterr().out


# --- integracion: datos descargados -> indice -> consola simulada ---------------------------


def _repo_con_actividad() -> DatosRepo:
    commit = Commit(
        sha="a" * 40,
        repo="org/app",
        autor="Ana",
        fecha="2026-01-05T10:00:00Z",
        mensaje="corrige bug",
        archivos=(Archivo("tests/t.py", 3, 1),),
    )
    return DatosRepo(
        repo="org/app", obtenido="2026-01-10", limites=Limites(1, 1, 1, 1), commits=(commit,)
    )


def test_integracion_cache_indice_y_consulta_simulada(tmp_path):
    """Flujo completo sin red: cache local -> perfiles -> indice -> chat con citas."""
    from devmetrics.indexacion import IndiceVectorial
    from devmetrics.recuperacion import RecuperadorCombinado

    CacheLocal(tmp_path).guardar(_repo_con_actividad())
    perfiles = IndiceVectorial(EmbeddingsBolsa(), ruta=None)
    n_repos, n_logins, res = indexar_perfiles(perfiles, str(tmp_path))
    assert (n_repos, n_logins) == (1, 1) and res.nuevos == 1

    conocimiento = IndiceVectorial(EmbeddingsBolsa(), ruta=None)
    recuperador = RecuperadorCombinado(conocimiento, perfiles)
    conv = Conversacion(recuperador, LLMSimulado())
    r = conv.preguntar("que hizo ana con las pruebas", desarrollador="ana")
    assert r.fuentes and "org/app / commits / @ana" in r.fuentes[0]


def test_recuperacion_vacia_no_llama_al_llm():
    class Vacio:
        def recuperar(self, *a, **k):
            return Recuperacion([])

    conv = Conversacion(Vacio(), _LLMQueFallaSiSeUsa())
    r = conv.preguntar("algo sin datos")
    assert not r.fuentes
