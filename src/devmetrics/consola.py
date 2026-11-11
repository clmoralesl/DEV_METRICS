"""Consola conversacional de DevMetrics: chat con streaming y comandos de ingesta e indexado.

Uso: python scripts/consola.py [chat|ingestar|indexar] ... (ver README). El recuperador y el LLM
son inyectables (`Consola`), de modo que las pruebas no dependen de red ni de modelos.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TextIO

from devmetrics.agente import Conversacion, Respuesta
from devmetrics.indexacion import RUTA_POR_DEFECTO
from devmetrics.llm import ErrorLLM

DIR_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
DATA_DIR = "data/github"
AYUDA = """Comandos:
  /ayuda                             esta ayuda
  /desarrollador <login>             limita las consultas a un desarrollador (sin login: quita)
  /reiniciar                         borra la memoria de la conversacion
  /ingestar <propietario/repo> ...   descarga actividad de GitHub (opciones de ingestar.py)
  /indexar [perfiles|conocimiento]   indexa los perfiles descargados o la base interna
  /salir                             termina (tambien Ctrl+D)
Cualquier otro texto se envia como pregunta al agente."""


def _cargar_script(nombre: str):
    """Los scripts de scripts/ son la unica implementacion de ingesta e indexado: se reutilizan."""
    ruta = DIR_SCRIPTS / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(f"scripts_{nombre}", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def ingestar(argv: list[str]) -> int:
    return _cargar_script("ingestar").main(argv)


def indexar_conocimiento(argv: list[str]) -> int:
    _cargar_script("indexar_conocimiento").main(argv)
    return 0


def logins_de(datos) -> set[str]:
    """Logins (en minusculas) con alguna actividad en los datos de un repositorio."""
    nombres: set[str | None] = set()
    for c in datos.commits:
        nombres.add(c.autor)
    for p in datos.pull_requests:
        nombres.add(p.autor)
    for r in datos.revisiones:
        nombres.add(r.revisor)
    for i in datos.issues:
        nombres.add(i.autor)
        nombres.update(i.asignados)
    return {n.casefold() for n in nombres if n}


def indexar_perfiles(indice, data_dir: str = DATA_DIR, logins: list[str] | None = None):
    """Indexa en `indice` los perfiles de los repositorios descargados en `data_dir`.

    Sin `logins`, indexa a todos los que tienen actividad. Devuelve (n_repos, n_logins,
    ResultadoIndexado) o None si no hay datos descargados.
    """
    from devmetrics.ingesta import CacheLocal
    from devmetrics.perfiles import documentos_de, segmentar

    cache = CacheLocal(data_dir)
    nombres = sorted(p.stem.replace("~", "/") for p in cache.directorio.glob("*.json"))
    repos = [d for d in (cache.cargar(n) for n in nombres) if d is not None]
    if not repos:
        return None
    todos = sorted({x for d in repos for x in logins_de(d)})
    elegidos = [x.casefold() for x in logins] if logins else todos
    chunks = [c for x in elegidos for c in segmentar(documentos_de(x, repos))]
    return len(repos), len(elegidos), indice.indexar(chunks)


class LLMSimulado:
    """LLM de demostracion sin red: responde con los fragmentos recuperados y sus citas.

    No razona ni resume: sirve para ver la recuperacion, las citas y el streaming sin clave ni
    modelo. Las respuestas reales las produce `ClienteLLM`.
    """

    _FRAGMENTO = re.compile(r"^\[\d+\] (.*?)\n {4}Fuente: (.*)$", re.MULTILINE | re.DOTALL)

    def invocar(self, mensajes) -> str:
        contexto = str(mensajes[-1]["content"])
        lineas = []
        for bloque in re.split(r"\n(?=\[\d+\] )", contexto):
            m = self._FRAGMENTO.match(bloque.strip())
            if m:
                primera = m.group(1).strip().splitlines()[0][:160]
                lineas.append(f"- {primera} ({m.group(2).strip()})")
        if not lineas:
            return "Evidencia insuficiente: el modo simulado no encontro fragmentos que citar."
        return "Respuesta simulada (sin LLM), fragmentos recuperados:\n" + "\n".join(lineas[:3])

    def flujo(self, mensajes) -> Iterator[str]:
        for palabra in re.findall(r"\S+\s*", self.invocar(mensajes)):
            yield palabra


class Consola:
    """Bucle de lectura y evaluacion sobre una `Conversacion`."""

    def __init__(
        self,
        conversacion: Conversacion,
        *,
        entrada: Callable[[str], str] = input,
        salida: TextIO | None = None,
        ingesta: Callable[[list[str]], int] = ingestar,
        indexado_perfiles: Callable[[], str] | None = None,
        indexado_conocimiento: Callable[[], str] | None = None,
    ):
        self._conv = conversacion
        self._entrada = entrada
        self._salida = salida or sys.stdout
        self._ingesta = ingesta
        self._idx_perfiles = indexado_perfiles
        self._idx_conocimiento = indexado_conocimiento
        self.desarrollador: str | None = None

    def _escribir(self, texto: str) -> None:
        self._salida.write(texto)
        self._salida.flush()

    def _linea(self, texto: str = "") -> None:
        self._escribir(texto + "\n")

    def ejecutar(self) -> int:
        self._linea("DevMetrics. Escribe una pregunta o /ayuda; /salir para terminar.")
        while True:
            try:
                texto = self._entrada("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._linea()
                return 0
            if not texto:
                continue
            if texto.startswith("/"):
                if self.comando(texto):
                    return 0
            else:
                self.preguntar(texto)

    def preguntar(self, texto: str) -> Respuesta | None:
        filtros = {"desarrollador": self.desarrollador} if self.desarrollador else {}
        try:
            r = self._conv.preguntar(texto, en_fragmento=self._escribir, **filtros)
        except ErrorLLM as error:
            self._linea(f"\nError del modelo: {error}")
            return None
        except ValueError as error:
            self._linea(f"\nConsulta no valida: {error}")
            return None
        except KeyboardInterrupt:
            self._linea("\nRespuesta interrumpida.")
            return None
        except Exception as error:  # noqa: BLE001 - un fallo de fuente no debe cerrar el chat
            self._linea(f"\nError al consultar las fuentes: {type(error).__name__}: {error}")
            return None
        self._linea()
        if r.fuentes:
            self._linea("Fuentes: " + "; ".join(r.fuentes))
        return r

    def comando(self, texto: str) -> bool:
        """Ejecuta un comando de barra. Devuelve True si hay que terminar."""
        try:
            partes = shlex.split(texto)
        except ValueError as error:
            self._linea(f"Comando mal formado: {error}")
            return False
        nombre, args = partes[0].lower(), partes[1:]
        if nombre in ("/salir", "/exit", "/q"):
            return True
        if nombre == "/ayuda":
            self._linea(AYUDA)
        elif nombre == "/reiniciar":
            self._conv.reiniciar()
            self._linea("Memoria de la conversacion borrada.")
        elif nombre == "/desarrollador":
            self.desarrollador = args[0].lstrip("@").casefold() if args else None
            self._linea(f"Filtro de desarrollador: {self.desarrollador or 'ninguno'}")
        elif nombre == "/ingestar":
            self._ejecutar_tarea(lambda: self._ingesta(args))
        elif nombre == "/indexar":
            destino = args[0] if args else "perfiles"
            accion = {"perfiles": self._idx_perfiles, "conocimiento": self._idx_conocimiento}.get(
                destino
            )
            if accion is None:
                self._linea("Uso: /indexar [perfiles|conocimiento]")
            else:
                self._ejecutar_tarea(lambda: self._linea(accion()))
        else:
            self._linea(f"Comando desconocido: {nombre}. Usa /ayuda.")
        return False

    def _ejecutar_tarea(self, tarea: Callable[[], object]) -> None:
        try:
            tarea()
        except SystemExit as salida:  # argparse de los scripts termina asi ante argumentos malos
            if salida.code not in (0, None):
                self._linea("La orden termino con error.")
        except Exception as error:  # noqa: BLE001 - la consola sigue viva ante fallos de red o disco
            self._linea(f"Error: {type(error).__name__}: {error}")


def _resumen_perfiles(indice, data_dir: str, logins: list[str] | None = None) -> str:
    r = indexar_perfiles(indice, data_dir, logins)
    if r is None:
        return f"No hay datos en {data_dir}. Ejecuta antes: ingestar propietario/repo."
    n_repos, n_logins, res = r
    return (
        f"{n_repos} repositorios, {n_logins} desarrolladores: nuevos={res.nuevos} "
        f"actualizados={res.actualizados} sin_cambios={res.sin_cambios} total={indice.contar()}"
    )


def _resumen_conocimiento(indice: str) -> str:
    indexar_conocimiento(["--indice", indice])  # el script imprime su propio resumen
    return "Base de conocimiento indexada."


def construir(args) -> Consola:
    """Ensambla indices, recuperador y LLM reales (o el simulado con --simulado)."""
    from dotenv import load_dotenv

    from devmetrics.conocimiento import crear_indice_interno
    from devmetrics.indexacion import IndiceVectorial
    from devmetrics.llm import ClienteLLM, ModeloEmbeddings
    from devmetrics.recuperacion import RecuperadorCombinado, crear_en_vivo

    load_dotenv()
    emb = ModeloEmbeddings()
    perfiles = IndiceVectorial(emb, ruta=args.indice)
    conocimiento = crear_indice_interno(emb, ruta=args.indice)
    en_vivo = None
    if args.repos:
        import os

        from devmetrics.ingesta import CacheLocal, ClienteGitHub

        cliente = ClienteGitHub(os.environ.get("GITHUB_TOKEN") or None)
        en_vivo = crear_en_vivo(args.repos, cliente, emb, cache=CacheLocal(args.data_dir))
    recuperador = RecuperadorCombinado(conocimiento, perfiles, en_vivo=en_vivo)
    llm = LLMSimulado() if args.simulado else ClienteLLM()
    conversacion = Conversacion(recuperador, llm, tecnica=args.tecnica)
    return Consola(
        conversacion,
        ingesta=ingestar,
        indexado_perfiles=lambda: _resumen_perfiles(perfiles, args.data_dir),
        indexado_conocimiento=lambda: _resumen_conocimiento(args.indice),
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="orden")
    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("--indice", default=RUTA_POR_DEFECTO, help="carpeta del indice Chroma")
    comunes.add_argument("--data-dir", default=DATA_DIR, help="cache de datos de GitHub")
    chat = sub.add_parser("chat", parents=[comunes], help="conversar con el agente (por defecto)")
    chat.add_argument("--simulado", action="store_true", help="LLM simulado, sin red ni clave")
    chat.add_argument("--tecnica", default="zero_shot", help="tecnica del prompt sistema")
    chat.add_argument("--repos", nargs="*", help="repositorios para consultar GitHub en vivo")
    chat.add_argument("--pregunta", help="responde una sola pregunta y termina")
    ing = sub.add_parser("ingestar", help="descarga datos de GitHub (argumentos de ingestar.py)")
    ing.add_argument("argumentos", nargs=argparse.REMAINDER)
    idx = sub.add_parser("indexar", parents=[comunes], help="indexa perfiles o conocimiento")
    idx.add_argument("destino", nargs="?", choices=["perfiles", "conocimiento"], default="perfiles")
    idx.add_argument("--login", action="append", help="solo este desarrollador (repetible)")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # consolas cp1252 no deben abortar el turno
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("chat", "ingestar", "indexar", "-h", "--help"):
        argv = ["chat", *argv]
    args = _parser().parse_args(argv)
    if args.orden == "ingestar":
        return ingestar(args.argumentos)
    if args.orden == "indexar":
        if args.destino == "conocimiento":
            return indexar_conocimiento(["--indice", args.indice])
        from devmetrics.indexacion import IndiceVectorial
        from devmetrics.llm import ModeloEmbeddings

        indice = IndiceVectorial(ModeloEmbeddings(), ruta=args.indice)
        print(_resumen_perfiles(indice, args.data_dir, args.login))
        return 0
    consola = construir(args)
    if args.pregunta:
        return 0 if consola.preguntar(args.pregunta) else 1
    return consola.ejecutar()


if __name__ == "__main__":
    raise SystemExit(main())
