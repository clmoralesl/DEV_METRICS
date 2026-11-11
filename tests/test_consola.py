import io

from embeddings_falsos import EmbeddingsBolsa

from devmetrics.agente import Conversacion
from devmetrics.consola import Consola, LLMSimulado, indexar_perfiles, logins_de
from devmetrics.indexacion import IndiceVectorial
from devmetrics.ingesta import CacheLocal, DatosRepo, Limites
from devmetrics.ingesta.esquema import Commit
from devmetrics.llm import ErrorProveedor
from devmetrics.recuperacion import Fragmento, Recuperacion


class RecuperadorFalso:
    def __init__(self, recuperacion):
        self.recuperacion = recuperacion
        self.filtros = []

    def recuperar(self, consulta, **filtros):
        self.filtros.append(filtros)
        return self.recuperacion


CON_DATOS = Recuperacion(
    [
        Fragmento("dev_a toca esquemas\notra linea", "[perfil:dev_a#1]", "indexado", 0.1),
        Fragmento("criterio interno", "[conocimiento:c1]", "interna", 0.2),
    ]
)


def consola(entradas, recuperacion=CON_DATOS, llm=None, **kw):
    salida = io.StringIO()
    lineas = iter(entradas)

    def entrada(_):
        try:
            return next(lineas)
        except StopIteration:
            raise EOFError from None

    recuperador = RecuperadorFalso(recuperacion)
    conv = Conversacion(recuperador, llm or LLMSimulado())
    c = Consola(conv, entrada=entrada, salida=salida, **kw)
    return c, salida, recuperador


def test_pregunta_muestra_respuesta_y_fuentes_y_termina_con_eof():
    c, salida, _ = consola(["quien toca esquemas"])
    assert c.ejecutar() == 0
    texto = salida.getvalue()
    assert "Respuesta simulada" in texto
    assert "- dev_a toca esquemas ([perfil:dev_a#1])" in texto
    assert "Fuentes: [perfil:dev_a#1]; [conocimiento:c1]" in texto


def test_salir_y_lineas_vacias():
    c, salida, rec = consola(["", "/salir", "no se lee"])
    assert c.ejecutar() == 0
    assert rec.filtros == []


def test_filtro_de_desarrollador_se_aplica_y_se_quita():
    c, _, rec = consola(["/desarrollador @Dev_A", "hola", "/desarrollador", "otra"])
    c.ejecutar()
    assert rec.filtros == [{"desarrollador": "dev_a"}, {}]


def test_comandos_ayuda_desconocido_y_reiniciar():
    c, salida, _ = consola(["/ayuda", "/nada", "pregunta", "/reiniciar"])
    c.ejecutar()
    texto = salida.getvalue()
    assert "/ingestar" in texto and "Comando desconocido: /nada" in texto
    assert "Memoria de la conversacion borrada" in texto


def test_ingestar_delega_y_un_fallo_no_cierra_la_consola():
    llamadas = []

    def ingesta(args):
        llamadas.append(args)
        if args == ["malo"]:
            raise OSError("sin red")
        return 0

    c, salida, _ = consola(
        ["/ingestar pallets/click --max-commits 5", "/ingestar malo", "/ingestar x"],
        ingesta=ingesta,
    )
    assert c.ejecutar() == 0
    assert llamadas[0] == ["pallets/click", "--max-commits", "5"]
    assert "Error: OSError: sin red" in salida.getvalue()
    assert len(llamadas) == 3


def test_indexar_elige_destino():
    c, salida, _ = consola(
        ["/indexar", "/indexar conocimiento", "/indexar otro"],
        indexado_perfiles=lambda: "perfiles listos",
        indexado_conocimiento=lambda: "conocimiento listo",
    )
    c.ejecutar()
    texto = salida.getvalue()
    assert "perfiles listos" in texto and "conocimiento listo" in texto
    assert "Uso: /indexar" in texto


def test_error_del_llm_se_informa_y_la_consola_sigue():
    class Roto:
        def invocar(self, mensajes):
            raise ErrorProveedor("gemini: caido")

    c, salida, _ = consola(["una pregunta", "/ayuda"], llm=Roto())
    assert c.ejecutar() == 0
    texto = salida.getvalue()
    assert "Error del modelo: gemini: caido" in texto and "/salir" in texto


def test_sin_resultados_responde_evidencia_insuficiente():
    c, salida, _ = consola(["quien?"], recuperacion=Recuperacion([], ["fuente caida"]))
    c.ejecutar()
    assert "Evidencia insuficiente" in salida.getvalue()


def test_llm_simulado_emite_por_trozos_y_cita_literalmente():
    mensajes = [{"role": "user", "content": CON_DATOS.formatear()}]
    trozos = list(LLMSimulado().flujo(mensajes))
    assert len(trozos) > 3
    assert "".join(trozos) == LLMSimulado().invocar(mensajes)


def _repo(autor_a="Dev_A"):
    commits = tuple(
        Commit(
            sha=f"{i:040d}",
            repo="org/app",
            autor=a,
            fecha=f"2026-01-0{i}T10:00:00Z",
            mensaje=f"cambio {i}",
        )
        for i, a in ((1, autor_a), (2, "dev_b"), (3, None))
    )
    return DatosRepo(
        repo="org/app", obtenido="2026-01-10", limites=Limites(1, 1, 1, 1), commits=commits
    )


def test_logins_de_ignora_anonimos_y_normaliza():
    assert logins_de(_repo()) == {"dev_a", "dev_b"}


def test_indexar_perfiles_desde_la_cache_es_idempotente(tmp_path):
    assert indexar_perfiles(IndiceVectorial(EmbeddingsBolsa(), ruta=None), str(tmp_path)) is None
    CacheLocal(tmp_path).guardar(_repo())
    indice = IndiceVectorial(EmbeddingsBolsa(), ruta=None)
    n_repos, n_logins, res = indexar_perfiles(indice, str(tmp_path))
    assert (n_repos, n_logins, res.nuevos) == (1, 2, 2)
    assert indexar_perfiles(indice, str(tmp_path))[2].sin_cambios == 2
    _, n, _ = indexar_perfiles(indice, str(tmp_path), logins=["DEV_B"])
    assert n == 1


def test_error_de_la_fuente_no_cierra_el_chat():
    class Falla:
        def recuperar(self, consulta, **filtros):
            raise OSError("chroma caido")

    salida = io.StringIO()
    lineas = iter(["pregunta", "/ayuda"])
    c = Consola(
        Conversacion(Falla(), LLMSimulado()),
        entrada=lambda _: next(lineas, "/salir"),
        salida=salida,
    )
    assert c.ejecutar() == 0
    assert "Error al consultar las fuentes: OSError: chroma caido" in salida.getvalue()


def test_main_enruta_por_defecto_a_chat_y_ingestar(monkeypatch):
    from devmetrics import consola as modulo

    recibido = {}

    class Falsa:
        def preguntar(self, texto):
            recibido["pregunta"] = texto
            return object()

    monkeypatch.setattr(modulo, "construir", lambda args: (recibido.update(args=args), Falsa())[1])
    monkeypatch.setattr(modulo, "ingestar", lambda argv: recibido.update(ingesta=argv) or 0)
    assert modulo.main(["--simulado", "--pregunta", "hola"]) == 0
    assert recibido["args"].simulado and recibido["pregunta"] == "hola"
    assert modulo.main(["ingestar", "pallets/click", "--max-commits", "5"]) == 0
    assert recibido["ingesta"] == ["pallets/click", "--max-commits", "5"]
