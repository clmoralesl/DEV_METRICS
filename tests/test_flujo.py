import httpx
import pytest
from langchain_core.messages import AIMessageChunk

from devmetrics.agente import Conversacion
from devmetrics.llm import ClienteLLM, ConfigLLM, ErrorSinRed, ErrorTodosFallaron
from devmetrics.recuperacion import Fragmento, Recuperacion


class ModeloFlujo:
    """`stream` entrega los trozos de `guion`; un elemento que es excepcion se lanza en su turno."""

    def __init__(self, *guion):
        self.guion = list(guion)
        self.llamadas = 0

    def stream(self, mensajes):
        self.llamadas += 1
        for paso in self.guion:
            if isinstance(paso, BaseException):
                raise paso
            yield AIMessageChunk(content=paso)


def cliente(principal, respaldo=None):
    modelos = {"gemini": principal}
    if respaldo is not None:
        modelos["ollama"] = respaldo
    return ClienteLLM(
        ConfigLLM(respaldo="ollama" if respaldo is not None else None),
        modelos=modelos,
        dormir=lambda s: None,
    )


def test_flujo_emite_trozos_y_registra_proveedor():
    c = cliente(ModeloFlujo("ho", "la", ""))
    assert list(c.flujo("hi")) == ["ho", "la"]
    assert c.ultimo_proveedor == "gemini"


def test_flujo_conmuta_al_respaldo_si_falla_antes_del_primer_trozo():
    c = cliente(ModeloFlujo(httpx.ConnectError("caido")), ModeloFlujo("desde ollama"))
    assert "".join(c.flujo("hi")) == "desde ollama"
    assert c.ultimo_proveedor == "ollama"


def test_flujo_propaga_el_corte_a_mitad_de_respuesta_sin_conmutar():
    respaldo = ModeloFlujo("no debe usarse")
    c = cliente(ModeloFlujo("par", httpx.ConnectError("corte")), respaldo)
    salida = []
    with pytest.raises(ErrorSinRed):
        for trozo in c.flujo("hi"):
            salida.append(trozo)
    assert salida == ["par"]
    assert respaldo.llamadas == 0


def test_flujo_respuesta_vacia_y_todos_fallaron():
    c = cliente(ModeloFlujo(""), ModeloFlujo(httpx.ConnectError("x")))
    with pytest.raises(ErrorTodosFallaron):
        list(c.flujo("hi"))
    assert c.ultimo_proveedor is None


class RecuperadorFalso:
    def __init__(self, recuperacion):
        self.recuperacion = recuperacion

    def recuperar(self, consulta, **filtros):
        return self.recuperacion


class LLMFlujo:
    def __init__(self):
        self.llamadas = []

    def flujo(self, mensajes):
        self.llamadas.append(mensajes)
        yield from ("dev_a es ", "Druid. ", "[perfil:dev_a#1]")

    def invocar(self, mensajes):
        self.llamadas.append(mensajes)
        return "respuesta [perfil:dev_a#1]"


class LLMSinFlujo:
    def invocar(self, mensajes):
        return "respuesta [perfil:dev_a#1]"


CON_DATOS = Recuperacion([Fragmento("dev_a toca esquemas", "[perfil:dev_a#1]", "indexado", 0.1)])


def test_streaming_entrega_los_trozos_y_arma_la_respuesta():
    trozos = []
    conv = Conversacion(RecuperadorFalso(CON_DATOS), LLMFlujo())
    r = conv.preguntar("quien es dev_a", en_fragmento=trozos.append)
    assert trozos == ["dev_a es ", "Druid. ", "[perfil:dev_a#1]"]
    assert r.texto == "dev_a es Druid. [perfil:dev_a#1]"
    assert r.fuentes == ["[perfil:dev_a#1]"]
    assert conv.memoria.formatear().endswith(r.texto)


def test_sin_callback_se_usa_invocar():
    llm = LLMFlujo()
    r = Conversacion(RecuperadorFalso(CON_DATOS), llm).preguntar("quien es dev_a")
    assert r.texto == "respuesta [perfil:dev_a#1]"


def test_sin_flujo_el_callback_recibe_el_texto_completo():
    trozos = []
    Conversacion(RecuperadorFalso(CON_DATOS), LLMSinFlujo()).preguntar(
        "quien es dev_a", en_fragmento=trozos.append
    )
    assert trozos == ["respuesta [perfil:dev_a#1]"]


def test_evidencia_insuficiente_tambien_se_emite_por_el_callback():
    trozos = []
    llm = LLMFlujo()
    vacia = Recuperacion([], ["fuente caida"])
    r = Conversacion(RecuperadorFalso(vacia), llm).preguntar("x?", en_fragmento=trozos.append)
    assert not r.evidencia_suficiente and llm.llamadas == []
    assert "".join(trozos) == r.texto


def test_flujo_con_contenido_en_bloques():
    class Bloques:
        def stream(self, mensajes):
            yield AIMessageChunk(content=[{"type": "text", "text": "ho"}])
            yield AIMessageChunk(content=[{"type": "text", "text": "la"}])

    assert "".join(cliente(Bloques()).flujo("hi")) == "hola"
