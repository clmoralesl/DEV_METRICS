import httpx
import pytest
from langchain_core import exceptions as lce
from langchain_core.messages import AIMessage

from devmetrics.llm import (
    ClienteLLM,
    ConfigLLM,
    ErrorAccesoDenegado,
    ErrorClaveInvalida,
    ErrorConfiguracion,
    ErrorCupoAgotado,
    ErrorProveedor,
    ErrorSinRed,
    ErrorTodosFallaron,
)
from devmetrics.llm.cliente import clasificar_error, construir_modelo


class ModeloSimulado:
    """Devuelve o lanza, en orden, los elementos de `guion`; el ultimo se repite."""

    def __init__(self, *guion):
        self.guion = list(guion)
        self.llamadas = 0

    def invoke(self, mensajes):
        paso = self.guion[min(self.llamadas, len(self.guion) - 1)]
        self.llamadas += 1
        if isinstance(paso, BaseException):
            raise paso
        return AIMessage(content=paso)


def cliente(principal, respaldo=None, **config):
    modelos = {"gemini": principal}
    if respaldo is not None:
        modelos["ollama"] = respaldo
    pausas = []
    c = ClienteLLM(
        ConfigLLM(respaldo="ollama" if respaldo is not None else None, **config),
        modelos=modelos,
        dormir=pausas.append,
    )
    c.pausas = pausas
    return c


def test_respuesta_directa():
    c = cliente(ModeloSimulado(" hola "))
    assert c.invocar("hi") == "hola"
    assert c.ultimo_proveedor == "gemini"


def test_reintenta_error_transitorio_y_exito():
    principal = ModeloSimulado(lce.ModelConnectionError("x"), "ok")
    c = cliente(principal)
    assert c.invocar("hi") == "ok"
    assert principal.llamadas == 2
    assert c.pausas == [1.0]


def test_limite_de_reintentos_y_conmutacion_al_respaldo():
    principal = ModeloSimulado(httpx.ConnectError("caido"))
    respaldo = ModeloSimulado("desde ollama")
    c = cliente(principal, respaldo, max_reintentos=2)
    assert c.invocar("hi") == "desde ollama"
    assert principal.llamadas == 3
    assert c.pausas == [1.0, 2.0]
    assert c.ultimo_proveedor == "ollama"


def test_cupo_agotado_no_reintenta_y_conmuta():
    principal = ModeloSimulado(lce.ModelRateLimitError("429"))
    c = cliente(principal, ModeloSimulado("respaldo"))
    assert c.invocar("hi") == "respaldo"
    assert principal.llamadas == 1


def test_clave_invalida_sin_respaldo_da_mensaje_claro():
    c = cliente(ModeloSimulado(lce.ModelAuthenticationError("401")))
    with pytest.raises(ErrorClaveInvalida, match="GOOGLE_API_KEY"):
        c.invocar("hi")


def test_fallan_ambos_proveedores():
    c = cliente(
        ModeloSimulado(lce.ModelRateLimitError("429")),
        ModeloSimulado(ConnectionError("sin ollama")),
        max_reintentos=0,
    )
    with pytest.raises(ErrorTodosFallaron) as info:
        c.invocar("hi")
    assert [type(e) for e in info.value.errores] == [ErrorCupoAgotado, ErrorSinRed]


def test_falta_clave_de_gemini_cae_al_respaldo():
    c = ClienteLLM(
        ConfigLLM(),
        modelos={"ollama": ModeloSimulado("respaldo")},
        env={},
        dormir=lambda s: None,
    )
    assert c.invocar("hi") == "respaldo"
    assert c.ultimo_proveedor == "ollama"


@pytest.mark.parametrize(
    "exc, esperado",
    [
        (lce.ModelRateLimitError("x"), ErrorCupoAgotado),
        (RuntimeError("RESOURCE_EXHAUSTED: cuota"), ErrorCupoAgotado),
        (lce.ModelAuthenticationError("x"), ErrorClaveInvalida),
        (RuntimeError("400 API key not valid. Please pass a valid API key."), ErrorClaveInvalida),
        (lce.ModelTimeoutError("x"), ErrorSinRed),
        (httpx.ConnectError("x"), ErrorSinRed),
        (ConnectionError("x"), ErrorSinRed),
        (ValueError("raro"), ErrorProveedor),
    ],
)
def test_clasificar_error(exc, esperado):
    assert type(clasificar_error(exc, "gemini")) is esperado


def test_clasificar_error_por_codigo_http():
    class ConCodigo(Exception):
        def __init__(self, code):
            self.code = code

    assert isinstance(clasificar_error(ConCodigo(429), "gemini"), ErrorCupoAgotado)
    assert isinstance(clasificar_error(ConCodigo(403), "gemini"), ErrorAccesoDenegado)


def test_mensaje_sin_red_de_ollama_orienta_al_usuario():
    assert "en ejecucion" in str(clasificar_error(ConnectionError("x"), "ollama"))


def test_config_valida_proveedores_y_limites():
    with pytest.raises(ErrorConfiguracion):
        ConfigLLM(proveedor="openai")
    with pytest.raises(ErrorConfiguracion):
        ConfigLLM(max_reintentos=-1)
    assert ConfigLLM(proveedor="ollama", respaldo="ollama").respaldo is None


def test_config_desde_entorno():
    c = ConfigLLM.desde_entorno(
        {"DEVMETRICS_LLM_PROVIDER": "Ollama", "DEVMETRICS_LLM_FALLBACK": "none"}
    )
    assert (c.proveedor, c.respaldo) == ("ollama", None)
    assert ConfigLLM.desde_entorno({}).proveedor == "gemini"


def test_construir_modelos_sin_red():
    config = ConfigLLM(temperature=0.2, max_tokens=50)
    gemini = construir_modelo("gemini", config, {"GOOGLE_API_KEY": "clave-de-prueba"})
    assert gemini.temperature == 0.2 and gemini.max_output_tokens == 50 and gemini.max_retries == 0
    ollama = construir_modelo("ollama", config, {"OLLAMA_HOST": "http://localhost:11434"})
    assert ollama.num_predict == 50 and ollama.temperature == 0.2


def test_construir_gemini_sin_clave_falla_con_mensaje():
    with pytest.raises(ErrorConfiguracion, match="aistudio"):
        construir_modelo("gemini", ConfigLLM(), {})


def test_reintentos_agotados_sin_respaldo_lanza_sin_red():
    principal = ModeloSimulado(ConnectionError("x"))
    c = cliente(principal, max_reintentos=1)
    with pytest.raises(ErrorSinRed):
        c.invocar("hi")
    assert principal.llamadas == 2


def test_error_no_clasificado_no_se_reintenta():
    principal = ModeloSimulado(ValueError("modelo no encontrado"))
    c = cliente(principal, ModeloSimulado("respaldo"))
    assert c.invocar("hi") == "respaldo"
    assert principal.llamadas == 1


def test_error_de_servidor_se_reintenta():
    class Servidor(Exception):
        code = 503

    principal = ModeloSimulado(Servidor("saturado"), "ok")
    assert cliente(principal).invocar("hi") == "ok"
    assert principal.llamadas == 2


def test_respuesta_vacia_conmuta_al_respaldo():
    principal = ModeloSimulado("   ")
    c = cliente(principal, ModeloSimulado("respaldo"))
    assert c.invocar("hi") == "respaldo"
    assert principal.llamadas == 1


def test_respuesta_vacia_sin_respaldo_es_error():
    with pytest.raises(ErrorProveedor, match="vacia"):
        cliente(ModeloSimulado("")).invocar("hi")


def test_clave_rechazada_de_ollama_no_menciona_google():
    class Denegado(Exception):
        status_code = 401

    mensaje = str(clasificar_error(Denegado("x"), "ollama"))
    assert "GOOGLE_API_KEY" not in mensaje and "401" in mensaje


def test_mensaje_de_error_enmascara_claves():
    clave = "AIza" + "x" * 35
    mensaje = str(clasificar_error(ValueError(f"fallo con key={clave}"), "gemini"))
    assert clave not in mensaje and "[clave]" in mensaje


def test_ultimo_proveedor_se_reinicia_si_falla():
    c = cliente(ModeloSimulado("ok", lce.ModelRateLimitError("x")))
    c.invocar("hi")
    with pytest.raises(ErrorCupoAgotado):
        c.invocar("hi")
    assert c.ultimo_proveedor is None


def test_config_numerica_desde_entorno_y_validaciones():
    c = ConfigLLM.desde_entorno(
        {
            "DEVMETRICS_LLM_TEMPERATURE": "0.3",
            "DEVMETRICS_LLM_MAX_TOKENS": "256",
            "DEVMETRICS_LLM_MAX_RETRIES": "1",
        }
    )
    assert (c.temperature, c.max_tokens, c.max_reintentos) == (0.3, 256, 1)
    with pytest.raises(ErrorConfiguracion, match="numerico"):
        ConfigLLM.desde_entorno({"DEVMETRICS_LLM_MAX_TOKENS": "mucho"})
    with pytest.raises(ErrorConfiguracion):
        ConfigLLM(temperature=3)
    with pytest.raises(ErrorConfiguracion):
        ConfigLLM(timeout=0)


def test_variables_vacias_de_env_example_usan_valores_por_defecto():
    c = ConfigLLM.desde_entorno(
        {
            "DEVMETRICS_LLM_PROVIDER": "",
            "DEVMETRICS_LLM_FALLBACK": "",
            "DEVMETRICS_GEMINI_MODEL": "",
            "DEVMETRICS_OLLAMA_MODEL": "",
        }
    )
    assert c == ConfigLLM()


def test_403_muestra_el_motivo_del_proveedor_y_no_culpa_a_la_clave():
    exc = lce.ModelPermissionDeniedError("The Gemini API free tier is not available")
    error = clasificar_error(exc, "gemini")
    assert isinstance(error, ErrorAccesoDenegado)
    assert "free tier" in str(error) and "clave rechazada" not in str(error)
