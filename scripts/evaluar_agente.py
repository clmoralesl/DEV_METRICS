"""Evalua el agente RAG con tests/casos_agente.json y regenera la tabla de pruebas.md.

Metricas: context precision y context recall (deterministas, contra las fuentes esperadas),
faithfulness y answer relevancy (LLM como juez, con cache en disco) y dos comprobaciones de
comportamiento: el perfil esperado y la abstencion con poca actividad.

Una sola orden regenera la tabla (las respuestas ya cacheadas no vuelven a pedirse):

    python scripts/evaluar_agente.py

Opciones utiles: --limite N (primeros N casos), --solo-recuperacion (sin LLM, sin clave),
--proveedor ollama, --trazas (LangSmith si LANGSMITH_API_KEY esta definida en el entorno).
Si la cuota del proveedor se agota, el script guarda lo avanzado, informa y termina sin reintentos.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from muestra_agregados import MIXTOS, POCA_ACTIVIDAD, POSITIVOS  # noqa: E402

from devmetrics.agente import Conversacion  # noqa: E402
from devmetrics.conocimiento import crear_indice_interno, indexar_conocimiento  # noqa: E402
from devmetrics.evaluacion import (  # noqa: E402
    CacheLLM,
    LLMConCache,
    answer_relevancy,
    clave_de_fuente,
    coincide_perfil,
    context_precision,
    context_recall,
    es_abstencion,
    faithfulness,
)
from devmetrics.indexacion import IndiceVectorial  # noqa: E402
from devmetrics.llm import ClienteLLM, ConfigLLM, ModeloEmbeddings  # noqa: E402
from devmetrics.recuperacion import RecuperadorCombinado  # noqa: E402

CASOS = RAIZ / "tests" / "casos_agente.json"
SALIDA = RAIZ / "documentacion" / "evaluacion_resultados.json"
PRUEBAS = RAIZ / "documentacion" / "pruebas.md"
CACHE = RAIZ / "data" / "evaluacion" / "cache_llm.json"
SEMILLA_ALIAS = 13  # la misma de evaluar_clasificacion.py: dev_NN no delata la clase
REPOSITORIO = "muestra-piloto"
INICIO, FIN = "<!-- evaluacion:inicio -->", "<!-- evaluacion:fin -->"
ENCABEZADO = "## Issue 16: evaluacion del agente"


def alias_neutros() -> dict[str, str]:
    """alias de la muestra (D1, L3...) -> dev_NN, con el reparto de la evaluacion del issue 13."""
    todos = [a for tabla in (POSITIVOS, MIXTOS, POCA_ACTIVIDAD) for a in tabla]
    orden = list(range(len(todos)))
    random.Random(SEMILLA_ALIAS).shuffle(orden)
    return {todos[i]: f"dev_{n:02d}" for n, i in enumerate(orden, 1)}


def _pct(x: float) -> str:
    return f"{round(100 * x)} %"


def documentos_perfil() -> list[Document]:
    """Un documento por desarrollador de la muestra, redactado a partir de sus agregados."""
    neutro = alias_neutros()
    docs = []
    for tabla in (POSITIVOS, MIXTOS, POCA_ACTIVIDAD):
        for alias, (_, infra, docs_front, pruebas, fix, revisiones, commits) in tabla.items():
            login = neutro[alias]
            codigo = max(0.0, 1.0 - infra - docs_front - pruebas)
            texto = (
                f"Actividad de {login} en {REPOSITORIO} (resumen de commits y revisiones)\n"
                f"Commits recientes analizados: {commits}. Revisiones de pull requests ajenos: "
                f"{revisiones}.\n"
                f"Archivos tocados: {_pct(infra)} infraestructura y despliegue, "
                f"{_pct(docs_front)} documentacion y frontend, {_pct(pruebas)} pruebas, "
                f"{_pct(codigo)} codigo general. Commits de correccion de errores: {_pct(fix)}."
            )
            docs.append(
                Document(
                    page_content=texto,
                    metadata={
                        "id": f"{login}|{REPOSITORIO}|resumen|0",
                        "desarrollador": login,
                        "repositorio": REPOSITORIO,
                        "tipo_fuente": "resumen",
                        "n_eventos": commits + revisiones,
                    },
                )
            )
    return docs


def construir_recuperador(embeddings) -> RecuperadorCombinado:
    interno = crear_indice_interno(embeddings, ruta=None)
    indexar_conocimiento(interno)
    perfiles = IndiceVectorial(embeddings, ruta=None)
    perfiles.indexar(documentos_perfil())
    return RecuperadorCombinado(interno, perfiles)


def _media(valores: Sequence[float | None]) -> float | None:
    validos = [v for v in valores if v is not None]
    return sum(validos) / len(validos) if validos else None


def evaluar_caso(caso: dict, recuperador, llm, embeddings) -> dict:
    """Con `llm=None` solo se mide la recuperacion (sin generar ni juzgar)."""
    filtros = {"desarrollador": caso["desarrollador"]} if caso.get("desarrollador") else {}
    esperadas = caso.get("fuentes_esperadas", [])
    fiel = relevancia = abstiene = perfil_ok = None
    texto = ""
    if llm is None:
        fragmentos = recuperador.recuperar(caso["pregunta"], **filtros).fragmentos
    else:
        respuesta = Conversacion(recuperador, llm).preguntar(caso["pregunta"], **filtros)
        fragmentos = respuesta.recuperacion.fragmentos if respuesta.recuperacion else []
        texto = respuesta.texto
        abstiene = es_abstencion(texto) or not respuesta.evidencia_suficiente
        perfil_ok = coincide_perfil(texto, caso.get("perfil_esperado"))
        if not abstiene:
            fiel = faithfulness(llm, respuesta.recuperacion.formatear(), texto)
            relevancia = answer_relevancy(llm, embeddings, caso["pregunta"], texto)
    return {
        "id": caso["id"],
        "grupo": caso["grupo"],
        "pregunta": caso["pregunta"],
        "perfil_esperado": caso.get("perfil_esperado"),
        "fuentes_esperadas": esperadas,
        "fuentes_recuperadas": [clave_de_fuente(f) for f in fragmentos],
        "context_precision": context_precision(fragmentos, esperadas),
        "context_recall": context_recall(fragmentos, esperadas),
        "faithfulness": fiel,
        "answer_relevancy": relevancia,
        "perfil_correcto": perfil_ok,
        "abstiene": abstiene if caso.get("perfil_esperado") else None,
        "respuesta": texto,
    }


def _celda(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _marca(v: bool | None) -> str:
    return "-" if v is None else ("si" if v else "no")


def resumen(resultados: list[dict]) -> dict:
    def tasa(filas: list[dict], clave: str) -> float | None:
        validos = [r[clave] for r in filas if r[clave] is not None]
        return sum(validos) / len(validos) if validos else None

    insuf = [r for r in resultados if r["perfil_esperado"] == "insuficiente"]
    return {
        "casos": len(resultados),
        "context_precision": _media([r["context_precision"] for r in resultados]),
        "context_recall": _media([r["context_recall"] for r in resultados]),
        "faithfulness": _media([r["faithfulness"] for r in resultados]),
        "answer_relevancy": _media([r["answer_relevancy"] for r in resultados]),
        "perfil_correcto": tasa(resultados, "perfil_correcto"),
        "abstencion_poca_actividad": tasa(insuf, "perfil_correcto"),
        "n_con_juez": sum(1 for r in resultados if r["faithfulness"] is not None),
    }


def tabla_markdown(resultados: list[dict], meta: dict) -> str:
    r = resumen(resultados)
    lineas = [
        f"Generada por `python scripts/evaluar_agente.py` ({meta['fecha']}; agente y juez: "
        f"{meta['modelo']}; {r['casos']} casos; juez en {r['n_con_juez']}).",
        "",
        "| Caso | Grupo | Precision | Recall | Fidelidad | Relevancia | Perfil | Abstencion |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in resultados:
        lineas.append(
            f"| {x['id']} | {x['grupo']} | {_celda(x['context_precision'])} | "
            f"{_celda(x['context_recall'])} | {_celda(x['faithfulness'])} | "
            f"{_celda(x['answer_relevancy'])} | {_marca(x['perfil_correcto'])} | "
            f"{_marca(x['abstiene'])} |"
        )
    lineas += [
        f"| **Media** | | **{_celda(r['context_precision'])}** | "
        f"**{_celda(r['context_recall'])}** | "
        f"**{_celda(r['faithfulness'])}** | **{_celda(r['answer_relevancy'])}** | "
        f"**{_celda(r['perfil_correcto'])}** | |",
    ]
    return "\n".join(lineas)


def actualizar_pruebas(ruta: Path, tabla: str) -> None:
    """Reemplaza el bloque entre marcadores; si no existe, agrega la seccion al final."""
    texto = ruta.read_text(encoding="utf-8")
    bloque = f"{INICIO}\n{tabla}\n{FIN}"
    if INICIO in texto and FIN in texto:
        nuevo = re.sub(
            re.escape(INICIO) + r".*?" + re.escape(FIN), lambda _: bloque, texto, flags=re.S
        )
    else:
        nuevo = texto.rstrip() + f"\n\n{ENCABEZADO}\n\n{bloque}\n"
    ruta.write_text(nuevo, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--proveedor", default="gemini", choices=["gemini", "ollama"])
    p.add_argument("--pausa", type=float, default=5.0, help="segundos entre llamadas reales")
    p.add_argument("--limite", type=int, default=None, help="evalua solo los primeros N casos")
    p.add_argument(
        "--solo-recuperacion", action="store_true", help="sin LLM: solo precision y recall"
    )
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--casos", default=str(CASOS))
    p.add_argument("--cache", default=str(CACHE))
    p.add_argument(
        "--salida",
        default=None,
        help="JSON de resultados (por defecto, solo en corridas completas)",
    )
    p.add_argument("--pruebas", default=str(PRUEBAS), help="archivo donde va la tabla")
    p.add_argument("--trazas", action="store_true", help="trazas en LangSmith (opcional)")
    return p


def _activar_trazas() -> None:
    if not os.environ.get("LANGSMITH_API_KEY"):
        sys.exit("--trazas requiere LANGSMITH_API_KEY en el entorno o en .env.")
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGSMITH_PROJECT", "devmetrics-evaluacion")


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    load_dotenv()
    if a.trazas:
        _activar_trazas()
    casos = json.loads(Path(a.casos).read_text(encoding="utf-8"))["casos"][: a.limite]
    embeddings = ModeloEmbeddings()
    recuperador = construir_recuperador(embeddings)
    if a.solo_recuperacion:
        llm, modelo = None, "sin LLM"
    else:
        config = ConfigLLM(
            proveedor=a.proveedor, respaldo=None, max_tokens=a.max_tokens, max_reintentos=0
        )
        modelo = f"{a.proveedor}:{getattr(config, 'modelo_' + a.proveedor)}"
        llm = LLMConCache(ClienteLLM(config), CacheLLM(a.cache), modelo, pausa=a.pausa)
    resultados: list[dict] = []
    parado = None
    for caso in casos:
        try:
            resultados.append(evaluar_caso(caso, recuperador, llm, embeddings))
        except Exception as error:  # el avance parcial no debe perderse por ningun fallo
            parado = f"{caso['id']}: {type(error).__name__}: {error}"
            break
        print(f"{caso['id']} listo", flush=True)
    if parado:
        print(f"Detenido sin reintentos en {parado}. Resultados parciales: {len(resultados)}.")
    meta = {"fecha": date.today().isoformat(), "modelo": modelo, "parado": parado}
    completa = not parado and not a.solo_recuperacion and a.limite is None
    destino = a.salida or (str(SALIDA) if completa else None)
    if destino:
        Path(destino).write_text(
            json.dumps(
                {"meta": meta, "resumen": resumen(resultados), "casos": resultados},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    if completa:
        actualizar_pruebas(Path(a.pruebas), tabla_markdown(resultados, meta))
        print(f"Tabla actualizada en {a.pruebas}")
    else:
        print(tabla_markdown(resultados, meta))
        print("(tabla y JSON versionado no escritos: corrida parcial, limitada o sin LLM)")
    return 1 if parado else 0


if __name__ == "__main__":
    sys.exit(main())
