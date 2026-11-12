import json

import pytest
from embeddings_falsos import EmbeddingsBolsa
from github_falso import RespuestaFalsa, SesionFalsa
from langchain_core.messages import AIMessageChunk

from devmetrics.ingesta import (
    CacheLocal,
    ClienteGitHub,
    ErrorAccesoDenegado,
    ErrorLimiteTasa,
    Limites,
)
from devmetrics.ingesta.esquema import VERSION_ESQUEMA, DatosRepo
from devmetrics.ingesta.ingesta import _issues, _numero_de_url
from devmetrics.llm import (
    ClienteLLM,
    ConfigLLM,
    ErrorConfiguracion,
    ErrorProveedor,
    ErrorTodosFallaron,
)
from devmetrics.llm.cliente import construir_modelo
from devmetrics.prompts import (
    ErrorPrompt,
    ErrorSalida,
    cargar,
    extraer_json,
    listar,
    validar_recomendacion,
)
from devmetrics.recuperacion import crear_herramienta_github

REPO = "acme/demo"
RUTA = "/repos/acme/demo/x"


def _cliente(respuestas, **kw):
    pausas = []
    ahora = kw.pop("ahora", lambda: 0.0)
    cliente = ClienteGitHub(
        "t",
        session=SesionFalsa({RUTA: respuestas}),
        dormir=pausas.append,
        ahora=ahora,
        **kw,
    )
    return cliente, pausas


# ingesta/cliente.py: espera por limite de tasa y respuesta inesperada


def test_cabecera_ratelimit_remaining_cero_espera_hasta_el_reset_mas_uno():
    limitada = RespuestaFalsa(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "130"})
    cliente, pausas = _cliente([limitada, RespuestaFalsa(200, {"ok": True})], ahora=lambda: 100.0)
    assert cliente.obtener(RUTA) == {"ok": True}
    assert pausas == [31.0]


def test_reset_ya_vencido_espera_solo_un_segundo():
    limitada = RespuestaFalsa(429, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "50"})
    cliente, pausas = _cliente([limitada, RespuestaFalsa(200, {"ok": True})], ahora=lambda: 100.0)
    cliente.obtener(RUTA)
    assert pausas == [1.0]


def test_reset_lejano_supera_la_espera_maxima_y_lanza_limite_de_tasa():
    limitada = RespuestaFalsa(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1000"})
    cliente, pausas = _cliente([limitada], ahora=lambda: 0.0)
    with pytest.raises(ErrorLimiteTasa):
        cliente.obtener(RUTA)
    assert pausas == []


@pytest.mark.parametrize("estado", [403, 429])
def test_texto_rate_limit_sin_cabeceras_espera_sesenta_segundos(estado):
    limitada = RespuestaFalsa(estado, {"message": "API Rate Limit exceeded"})
    cliente, pausas = _cliente([limitada, RespuestaFalsa(200, {"ok": True})])
    assert cliente.obtener(RUTA) == {"ok": True}
    assert pausas == [60.0]


def test_403_sin_pistas_de_limite_es_acceso_denegado_sin_esperar():
    respuesta = RespuestaFalsa(403, {"message": "forbidden"}, {"X-RateLimit-Remaining": "5"})
    cliente, pausas = _cliente([respuesta])
    with pytest.raises(ErrorAccesoDenegado, match="acceso denegado"):
        cliente.obtener(RUTA)
    assert pausas == []


def test_respuesta_http_inesperada_lanza_acceso_denegado():
    cliente, _ = _cliente([RespuestaFalsa(418, {})])
    with pytest.raises(ErrorAccesoDenegado, match="respuesta inesperada 418"):
        cliente.obtener(RUTA)


# ingesta/esquema.py y cache: version de esquema


def _datos_validos():
    limites = Limites(1, 1, 1, 1)
    return DatosRepo(repo=REPO, obtenido="2025-01-01T00:00:00Z", limites=limites)


def test_version_de_esquema_distinta_no_es_compatible():
    d = _datos_validos().a_dict()
    d["version"] = VERSION_ESQUEMA + 1
    with pytest.raises(ValueError, match="version de esquema no compatible"):
        DatosRepo.desde_dict(d)
    del d["version"]
    with pytest.raises(ValueError, match="version de esquema no compatible"):
        DatosRepo.desde_dict(d)


def test_cache_con_version_antigua_se_descarta(tmp_path):
    cache = CacheLocal(tmp_path)
    d = _datos_validos().a_dict()
    d["version"] = VERSION_ESQUEMA + 1
    cache.ruta(REPO).write_text(json.dumps(d), encoding="utf-8")
    assert cache.cargar(REPO) is None


def test_cache_inexistente_devuelve_none(tmp_path):
    assert CacheLocal(tmp_path).cargar(REPO) is None


# ingesta/ingesta.py


@pytest.mark.parametrize(
    "url, esperado",
    [
        (None, 0),
        ("", 0),
        ("sin-barras", 0),
        ("https://api.github.com/repos/a/b/issues/abc", 0),
        ("https://api.github.com/repos/a/b/issues/", 0),
        ("https://api.github.com/repos/a/b/issues/42", 42),
        ("https://api.github.com/repos/a/b/pulls/7/", 7),
    ],
)
def test_numero_de_url_tolera_entradas_invalidas(url, esperado):
    assert _numero_de_url(url) == esperado


def _issue(numero, **extra):
    return {"number": numero, "title": f"t{numero}", "state": "open", **extra}


def test_listado_de_issues_omite_pr_y_respeta_el_maximo():
    elementos = [
        _issue(1, pull_request={"url": "x"}),
        _issue(2),
        _issue(3, pull_request={}),
        _issue(4),
        _issue(5),
    ]
    sesion = SesionFalsa({f"/repos/{REPO}/issues": [elementos]})
    cliente = ClienteGitHub("t", session=sesion, dormir=lambda s: None)
    issues = _issues(cliente, REPO, Limites(1, 1, 2, 1))
    assert [i.numero for i in issues] == [2, 4]


def test_listado_de_issues_vacio_y_con_asignados_nulos():
    sesion = SesionFalsa({f"/repos/{REPO}/issues": [[_issue(1, assignees=None), _issue(2)]]})
    cliente = ClienteGitHub("t", session=sesion, dormir=lambda s: None)
    issues = _issues(cliente, REPO, Limites(1, 1, 5, 1))
    assert [i.asignados for i in issues] == [(), ()]
    sesion_vacia = SesionFalsa({f"/repos/{REPO}/issues": [[]]})
    vacio = ClienteGitHub("t", session=sesion_vacia, dormir=lambda s: None)
    assert _issues(vacio, REPO, Limites(1, 1, 5, 1)) == ()


# llm/cliente.py


class ModeloFlujo:
    """Emite como fragmentos los elementos de `guion`; una excepcion se lanza al llegar a ella."""

    def __init__(self, *guion):
        self.guion = guion

    def stream(self, mensajes):
        for paso in self.guion:
            if isinstance(paso, BaseException):
                raise paso
            yield AIMessageChunk(content=paso)


def _cliente_llm(principal, respaldo=None):
    modelos = {"gemini": principal}
    if respaldo is not None:
        modelos["ollama"] = respaldo
    return ClienteLLM(
        ConfigLLM(respaldo="ollama" if respaldo is not None else None),
        modelos=modelos,
        dormir=lambda s: None,
    )


def test_proveedor_desconocido_es_error_de_configuracion():
    with pytest.raises(ErrorConfiguracion, match="Proveedor desconocido: 'openai'"):
        construir_modelo("openai", ConfigLLM())


def test_flujo_con_un_solo_proveedor_fallido_relanza_ese_error():
    c = _cliente_llm(ModeloFlujo(ValueError("boom")))
    with pytest.raises(ErrorProveedor, match="gemini: ValueError: boom"):
        list(c.flujo("hola"))
    assert c.ultimo_proveedor is None


def test_flujo_con_ambos_proveedores_fallidos_lanza_todos_fallaron():
    c = _cliente_llm(ModeloFlujo(ValueError("a")), ModeloFlujo(ValueError("b")))
    with pytest.raises(ErrorTodosFallaron):
        list(c.flujo("hola"))


def test_flujo_conmuta_al_respaldo_si_el_principal_falla_antes_de_emitir():
    c = _cliente_llm(ModeloFlujo(ValueError("a")), ModeloFlujo("hola ", "mundo"))
    assert "".join(c.flujo("x")) == "hola mundo"
    assert c.ultimo_proveedor == "ollama"


def test_flujo_sin_texto_es_error_de_respuesta_vacia():
    c = _cliente_llm(ModeloFlujo(""))
    with pytest.raises(ErrorProveedor, match="respuesta vacia"):
        list(c.flujo("x"))


# prompts/biblioteca.py

BASE = """
nombre = "p"
version = "1.0.0"
requisito = "RF0"
salida = "texto"
objetivo = "o"
[componentes]
rol = "r"
tarea = "t"
formato = "f"
restricciones = "x"
entrada = "{{a}}"
[validacion]
estado = "pendiente"
"""


def _escribir(directorio, nombre, texto):
    (directorio / f"{nombre}.toml").write_text(texto, encoding="utf-8")


def test_prompt_con_toml_invalido_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", 'nombre = "p\nversion = ')
    with pytest.raises(ErrorPrompt, match="TOML invalido en p.toml"):
        cargar("p", tmp_path)


def test_prompt_inexistente_en_directorio_dado_nombra_el_directorio(tmp_path):
    with pytest.raises(ErrorPrompt, match="no existe el prompt 'p'"):
        cargar("p", tmp_path)


def test_nombre_del_archivo_y_campo_nombre_deben_coincidir(tmp_path):
    _escribir(tmp_path, "otro", BASE)
    with pytest.raises(ErrorPrompt, match="no coincide"):
        cargar("otro", tmp_path)


@pytest.mark.parametrize(
    "campo, original", [("objetivo", 'objetivo = "o"'), ("requisito", 'requisito = "RF0"')]
)
def test_objetivo_o_requisito_vacio_se_rechaza(tmp_path, campo, original):
    texto = BASE.replace(original, f'{campo} = "  "')
    _escribir(tmp_path, "p", texto)
    with pytest.raises(ErrorPrompt, match=f"falta {campo}"):
        cargar("p", tmp_path)


def test_objetivo_ausente_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", BASE.replace('objetivo = "o"\n', ""))
    with pytest.raises(ErrorPrompt, match="falta objetivo"):
        cargar("p", tmp_path)


def test_salida_invalida_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", BASE.replace('salida = "texto"', 'salida = "xml"'))
    with pytest.raises(ErrorPrompt, match="salida invalida"):
        cargar("p", tmp_path)


def test_salida_json_con_validador_registrado_carga(tmp_path):
    texto = BASE.replace('nombre = "p"', 'nombre = "tipo_cambio"').replace(
        'salida = "texto"', 'salida = "json"'
    )
    _escribir(tmp_path, "tipo_cambio", texto)
    assert cargar("tipo_cambio", tmp_path).salida == "json"


def test_componentes_ausentes_se_listan(tmp_path):
    texto = BASE.split("[componentes]")[0] + '[validacion]\nestado = "pendiente"\n'
    _escribir(tmp_path, "p", texto)
    with pytest.raises(ErrorPrompt, match="componentes ausentes o vacios en 'p'"):
        cargar("p", tmp_path)


def test_falta_la_seccion_validacion(tmp_path):
    _escribir(tmp_path, "p", BASE.split("[validacion]")[0])
    with pytest.raises(ErrorPrompt, match="falta la seccion validacion"):
        cargar("p", tmp_path)


def test_validacion_sin_estado_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", BASE.replace('estado = "pendiente"', 'nota = "x"'))
    with pytest.raises(ErrorPrompt, match="falta la seccion validacion"):
        cargar("p", tmp_path)


def test_listar_directorio_ordenado_e_ignora_otras_extensiones(tmp_path):
    for nombre in ("zeta", "alfa", "medio"):
        _escribir(tmp_path, nombre, BASE)
    (tmp_path / "notas.txt").write_text("x", encoding="utf-8")
    assert listar(tmp_path) == ["alfa", "medio", "zeta"]
    assert listar(tmp_path / "no_existe") == []


# prompts/validadores.py


def test_extraer_json_con_llave_inicial_invalida_y_sin_otro_objeto_falla():
    with pytest.raises(ErrorSalida, match="no contiene un objeto JSON valido"):
        extraer_json("texto { no es json y no hay mas")
    with pytest.raises(ErrorSalida):
        extraer_json("[1, 2, 3]")


def test_extraer_json_salta_un_primer_corchete_que_no_es_objeto():
    assert extraer_json('prefijo {"a": [1]}') == {"a": [1]}
    with pytest.raises(ErrorSalida):
        extraer_json("")
    with pytest.raises(ErrorSalida):
        extraer_json(None)


def _recomendacion(**cambios):
    base = {
        "evidencia_suficiente": True,
        "respuesta": "r",
        "candidatos": [{"alias": "a", "justificacion": "j", "fuentes": ["p1"]}],
        "fuentes": ["p1"],
        "faltante": "",
    }
    return {**base, **cambios}


def test_recomendacion_con_fuentes_que_no_son_lista_es_error():
    with pytest.raises(ErrorSalida, match="fuentes debe ser una lista de identificadores"):
        validar_recomendacion(_recomendacion(fuentes="p1"), ["p1"])
    with pytest.raises(ErrorSalida, match="fuentes debe ser una lista de identificadores"):
        validar_recomendacion(_recomendacion(fuentes=["p1", ""]), ["p1"])


def test_recomendacion_con_candidatos_que_no_son_lista_es_error():
    with pytest.raises(ErrorSalida, match="candidatos debe ser una lista"):
        validar_recomendacion(_recomendacion(candidatos={"alias": "a"}), ["p1"])


# recuperacion/en_vivo.py


class ClienteQueExplota:
    llamadas = 0

    def __getattr__(self, nombre):
        raise RuntimeError("cliente roto")


def test_herramienta_en_vivo_reporta_el_fallo_de_la_consulta(tmp_path):
    herramienta = crear_herramienta_github(
        ClienteQueExplota(), EmbeddingsBolsa(), cache=CacheLocal(tmp_path)
    )
    salida = herramienta.invoke({"consulta": "x", "desarrollador": "dev", "repositorios": [REPO]})
    assert salida.startswith("SIN RESULTADOS (fallo de la consulta en vivo: ")
    assert "RuntimeError" in salida and "cliente roto" in salida


def test_version_no_semantica_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", BASE.replace('version = "1.0.0"', 'version = "v1"'))
    with pytest.raises(ErrorPrompt, match="version invalida en 'p'"):
        cargar("p", tmp_path)


def test_salida_json_sin_validador_registrado_se_rechaza(tmp_path):
    _escribir(tmp_path, "p", BASE.replace('salida = "texto"', 'salida = "json"'))
    with pytest.raises(ErrorPrompt, match="salida json pero no validador"):
        cargar("p", tmp_path)
