"""Compara zero-shot, few-shot y cadena de pensamiento sobre el prompt tipo_cambio.

Llama a la API REST de Ollama (sin el parametro `format`, para medir la consistencia real del
formato) y guarda las mediciones en documentacion/comparacion_prompts_resultados.json.

Uso: python scripts/comparar_prompts.py [--modelo M] [--repeticiones N] [--limite N] [--pensar]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from devmetrics.prompts import TECNICAS, ErrorSalida, cargar, validar_salida  # noqa: E402

CASOS = RAIZ / "tests" / "casos_prompts" / "tipo_cambio.json"
SALIDA = RAIZ / "documentacion" / "comparacion_prompts_resultados.json"
TEMPERATURA = 0.3


def llamar(
    host: str, modelo: str, mensajes: list[dict], semilla: int, pensar: bool, maximo: int
) -> dict:
    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "stream": False,
        "options": {"temperature": TEMPERATURA, "seed": semilla, "num_predict": maximo},
    }
    if not pensar:
        cuerpo["think"] = False
    inicio = time.perf_counter()
    respuesta = requests.post(f"{host}/api/chat", json=cuerpo, timeout=900)
    respuesta.raise_for_status()
    datos = respuesta.json()
    return {
        "texto": datos["message"]["content"],
        "tokens_entrada": datos.get("prompt_eval_count", 0),
        "tokens_salida": datos.get("eval_count", 0),
        "segundos": time.perf_counter() - inicio,
    }


def evaluar(
    host: str, modelo: str, repeticiones: int, limite: int | None, pensar: bool, maximo: int
) -> dict:
    prompt = cargar("tipo_cambio")
    casos = json.loads(CASOS.read_text(encoding="utf-8"))[:limite]
    registros = []
    for tecnica in TECNICAS:
        for caso in casos:
            variables = {"mensaje": caso["mensaje"], "archivos": _lista(caso["archivos"])}
            mensajes = prompt.mensajes(variables, tecnica)
            for repeticion in range(1, repeticiones + 1):
                medicion = llamar(host, modelo, mensajes, repeticion, pensar, maximo)
                try:
                    tipo = validar_salida("tipo_cambio", medicion["texto"])["tipo"]
                    error = None
                except ErrorSalida as excepcion:
                    tipo, error = None, str(excepcion)
                registros.append(
                    {
                        "tecnica": tecnica,
                        "caso": caso["id"],
                        "repeticion": repeticion,
                        "esperado": caso["esperado"],
                        "obtenido": tipo,
                        "error_formato": error,
                        "tokens_entrada": medicion["tokens_entrada"],
                        "tokens_salida": medicion["tokens_salida"],
                        "segundos": round(medicion["segundos"], 2),
                        "texto": medicion["texto"],
                    }
                )
                print(f"{tecnica} {caso['id']} r{repeticion}: {tipo or 'FORMATO'}", flush=True)
    return {
        "modelo": modelo,
        "prompt_version": prompt.version,
        "pensamiento_nativo": pensar,
        "temperatura": TEMPERATURA,
        "repeticiones": repeticiones,
        "casos": len(casos),
        "resumen": {t: _resumen([r for r in registros if r["tecnica"] == t]) for t in TECNICAS},
        "registros": registros,
    }


def _lista(archivos: list[str]) -> str:
    return "\n".join(f"- {a}" for a in archivos) if archivos else "(sin archivos listados)"


def _resumen(registros: list[dict]) -> dict:
    n = len(registros)
    validos = [r for r in registros if r["obtenido"]]
    aciertos = [r for r in validos if r["obtenido"] == r["esperado"]]
    return {
        "llamadas": n,
        "formato_valido_pct": round(100 * len(validos) / n, 1),
        "exactitud_pct": round(100 * len(aciertos) / n, 1),
        "tokens_entrada_media": round(statistics.mean(r["tokens_entrada"] for r in registros), 1),
        "tokens_salida_media": round(statistics.mean(r["tokens_salida"] for r in registros), 1),
        "segundos_media": round(statistics.mean(r["segundos"] for r in registros), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default="qwen3:4b")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--repeticiones", type=int, default=2)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument(
        "--pensar", action="store_true", help="deja activo el pensamiento nativo del modelo"
    )
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--salida", default=str(SALIDA))
    argumentos = parser.parse_args()
    if argumentos.limite is not None and argumentos.limite < 1:
        sys.exit("--limite debe ser al menos 1")
    try:
        resultados = evaluar(
            argumentos.host,
            argumentos.modelo,
            argumentos.repeticiones,
            argumentos.limite,
            argumentos.pensar,
            argumentos.max_tokens,
        )
    except requests.RequestException as error:
        sys.exit(f"Fallo de red o de Ollama: {error}")
    Path(argumentos.salida).write_text(
        json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(resultados["resumen"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
