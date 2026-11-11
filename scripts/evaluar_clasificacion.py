"""Evalua la clasificacion por arquetipos con un LLM real (Ollama) sobre la muestra etiquetada.

Casos: 15 positivos (5 por clase), 4 mixtos y 4 de poca actividad (sinteticos, volumen < minimo).
Guarda resultados y discrepancias frente al modelo de reglas (issue 4) en
documentacion/clasificacion_resultados.json.

Uso: python scripts/evaluar_clasificacion.py [--modelo M] [--limite N] [--tecnica cot]

Reproduce lo reportado (Ollama con qwen3:4b):
    python scripts/evaluar_clasificacion.py --modelo qwen3:4b --esquema \\
        --salida documentacion/clasificacion_resultados_qwen3-4b_esquema.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from muestra_agregados import MIXTOS, POCA_ACTIVIDAD, POSITIVOS, senales  # noqa: E402

from devmetrics.agente import clasificar  # noqa: E402
from devmetrics.arquetipos import cargar  # noqa: E402
from devmetrics.llm import ClienteLLM, ConfigLLM, ErrorLLM  # noqa: E402
from devmetrics.prompts import cargar as cargar_prompt  # noqa: E402

SALIDA = RAIZ / "documentacion" / "clasificacion_resultados.json"
TEMPERATURA = 0.3
# Reparto declarado antes de medir: se afina el prompt con AJUSTE y se reporta tambien PRUEBA.
PRUEBA = ("D4", "D5", "B4", "B5", "C4", "C5")
SEMILLA_ALIAS = 13  # el LLM recibe alias neutros: el alias de la muestra delata la clase
SIN_PENSAR = "\n/no_think"
BAJAS = ("baja", "datos_insuficientes")
ESQUEMA = {
    "type": "object",
    "properties": {
        "razonamiento": {"type": "string"},
        "mezcla": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in ("Druid", "Cleric", "Bard")},
            "required": ["Druid", "Cleric", "Bard"],
        },
        "dominante": {"type": "string", "enum": ["Druid", "Cleric", "Bard", "mixto"]},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja", "datos_insuficientes"]},
        "evidencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fuente": {"type": "string"}, "descripcion": {"type": "string"}},
                "required": ["fuente", "descripcion"],
            },
        },
        "faltante": {"type": "string"},
    },
    "required": ["razonamiento", "mezcla", "dominante", "confianza", "evidencias", "faltante"],
}
NOMBRE = {"druid": "Druid", "cleric": "Cleric", "bard": "Bard", "mixto": "mixto"}


class OllamaDirecto:
    def __init__(self, host: str, modelo: str, maximo: int, esquema: bool = False):
        self.host, self.modelo, self.maximo, self.esquema = host, modelo, maximo, esquema
        self.ultima: dict = {}

    def invocar(self, mensajes: list[dict]) -> str:
        # qwen3 ignora think:false; "/no_think" en el ultimo mensaje es su interruptor suave
        ultimo = {**mensajes[-1], "content": mensajes[-1]["content"] + SIN_PENSAR}
        cuerpo = {
            "model": self.modelo,
            "messages": [*mensajes[:-1], ultimo],
            "stream": False,
            "think": False,
            "options": {"temperature": TEMPERATURA, "seed": 1, "num_predict": self.maximo},
        }
        if self.esquema:
            cuerpo["format"] = ESQUEMA
        respuesta = requests.post(f"{self.host}/api/chat", json=cuerpo, timeout=900)
        respuesta.raise_for_status()
        datos = respuesta.json()
        mensaje = datos["message"]
        self.ultima = {
            "done_reason": datos.get("done_reason"),
            "eval_count": datos.get("eval_count"),
            "largo_contenido": len(mensaje.get("content", "")),
            "largo_pensamiento": len(mensaje.get("thinking", "") or ""),
        }
        return mensaje["content"]


class GeminiDirecto:
    """Gemini a traves del cliente del proyecto, sin respaldo: un fallo debe verse, no ocultarse."""

    esquema = False

    def __init__(self, maximo: int, pausa: float):
        self.cliente = ClienteLLM(ConfigLLM(proveedor="gemini", respaldo=None, max_tokens=maximo))
        self.modelo = getattr(self.cliente.config, "modelo_gemini", "gemini")
        self.pausa = pausa
        self.ultima: dict = {}

    def invocar(self, mensajes: list[dict]) -> str:
        time.sleep(self.pausa)  # la capa gratuita limita las solicitudes por minuto
        texto = self.cliente.invocar(mensajes)
        self.ultima = {"proveedor": self.cliente.ultimo_proveedor, "largo_contenido": len(texto)}
        return texto


def casos() -> list[tuple[str, str, str, tuple]]:
    filas = [("positivo", POSITIVOS), ("mixto", MIXTOS), ("poca_actividad", POCA_ACTIVIDAD)]
    return [
        (grupo, alias, fila[0], fila) for grupo, tabla in filas for alias, fila in tabla.items()
    ]


def evaluar(llm: OllamaDirecto, tecnica: str, limite: int | None, alias: list[str] | None) -> dict:
    config = cargar()
    registros = []
    todos = casos()
    orden = list(range(len(todos)))
    random.Random(SEMILLA_ALIAS).shuffle(orden)
    neutral = {todos[i][1]: f"dev_{n:02d}" for n, i in enumerate(orden, 1)}
    seleccion = [c for c in todos if not alias or c[1] in alias]
    for grupo, nombre, esperada, fila in seleccion[:limite]:
        inicio = time.perf_counter()
        resultado = clasificar(
            neutral[nombre], senales(fila), llm, config, tecnica=tecnica, omitir_no_medidas=True
        )
        registros.append(
            {
                "grupo": grupo,
                "alias_etiqueta": nombre,
                "esperada": NOMBRE[esperada],
                "segundos": round(time.perf_counter() - inicio, 1),
                "ultima_llamada": dict(llm.ultima),
                **resultado.a_dict(),
            }
        )
        print(f"{nombre}: esperada={NOMBRE[esperada]} llm={resultado.dominante}", flush=True)
    return {
        "modelo": llm.modelo,
        "tecnica": tecnica,
        "salida_restringida_por_esquema": llm.esquema,
        "alias_neutros": True,
        "evidencia_sin_campos_no_medidos": True,
        "prompt_version": cargar_prompt("clasificacion_arquetipo").version,
        "temperatura": TEMPERATURA,
        "fecha": date.today().isoformat(),
        "resumen": resumir(registros),
        "registros": registros,
    }


def resumir(registros: list[dict]) -> dict:
    positivos = [r for r in registros if r["grupo"] == "positivo"]
    poca = [r for r in registros if r["grupo"] == "poca_actividad"]
    mixtos = [r for r in registros if r["grupo"] == "mixto"]
    validos = [r for r in registros if r["valida"]]

    def acuerdo(lista: list[dict], clave: str) -> str:
        return f"{sum(1 for r in lista if r[clave])}/{len(lista)}"

    for r in registros:
        r["acierta_llm"] = r["valida"] and r["dominante"] == r["esperada"]
        reglas = r["discrepancia"]["dominante_reglas"]
        r["acierta_reglas"] = reglas == r["esperada"]
    return {
        "llamadas": len(registros),
        "formato_invalido": len(registros) - len(validos),
        "reintentos": sum(1 for r in registros if r["intentos"] > 1),
        "positivos_acuerdo_llm": acuerdo(positivos, "acierta_llm"),
        "positivos_acuerdo_reglas": acuerdo(positivos, "acierta_reglas"),
        "positivos_acuerdo_llm_pct": _pct(positivos, "acierta_llm"),
        "positivos_acuerdo_entre_validos": acuerdo(
            [r for r in positivos if r["valida"]], "acierta_llm"
        ),
        "positivos_con_salida_valida": acuerdo([{**r, "ok": r["valida"]} for r in positivos], "ok"),
        "fallos_por_causa": _causas(registros),
        "positivos_acuerdo_llm_prueba": acuerdo(
            [r for r in positivos if r["alias_etiqueta"] in PRUEBA], "acierta_llm"
        ),
        "positivos_acuerdo_llm_ajuste": acuerdo(
            [r for r in positivos if r["alias_etiqueta"] not in PRUEBA], "acierta_llm"
        ),
        "con_correccion_de_dominante": sum(
            1 for r in registros if any(c.startswith("dominante") for c in r["correcciones"])
        ),
        "con_mezcla_renormalizada": sum(
            1 for r in registros if any(c.startswith("mezcla") for c in r["correcciones"])
        ),
        "positivos_tendencia_llm_entre_validos": _tendencia(positivos),
        "mixtos_acuerdo_llm": acuerdo(mixtos, "acierta_llm"),
        "mixtos_acuerdo_reglas": acuerdo(mixtos, "acierta_reglas"),
        "poca_actividad_confianza_baja_llm_crudo": (
            f"{sum(1 for r in poca if r['cumplia_guardia'])}/{len(poca)}"
        ),
        "poca_actividad_confianza_baja_con_guardia": (
            f"{sum(1 for r in poca if r['valida'] and r['confianza'] in BAJAS)}/{len(poca)}"
        ),
        "discrepancias_dominante_vs_reglas": sum(
            1 for r in registros if r["discrepancia"].get("difiere_dominante")
        ),
    }


def _causas(registros: list[dict]) -> dict:
    causas: dict[str, int] = {}
    for r in registros:
        if not r["valida"]:
            clave = r["errores"][0].split(";")[0][:40] if r["errores"] else "sin detalle"
            clave = "la mezcla no suma 1" if clave.startswith("la mezcla suma") else clave
            causas[clave] = causas.get(clave, 0) + 1
    return causas


def _tendencia(positivos: list[dict]) -> str:
    """Clase con mayor puntaje en la mezcla del LLM frente a la etiqueta (solo salidas validas)."""
    validos = [r for r in positivos if r["valida"]]
    aciertos = sum(1 for r in validos if max(r["mezcla"], key=r["mezcla"].get) == r["esperada"])
    return f"{aciertos}/{len(validos)}"


def _pct(lista: list[dict], clave: str) -> float:
    return round(100 * sum(1 for r in lista if r[clave]) / len(lista), 1) if lista else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default="qwen3:4b")
    parser.add_argument(
        "--proveedor", default="ollama", choices=["ollama", "gemini"], help="LLM a evaluar"
    )
    parser.add_argument("--pausa", type=float, default=5.0, help="segundos entre llamadas (Gemini)")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--tecnica", default="cot", choices=["zero_shot", "few_shot", "cot"])
    parser.add_argument(
        "--esquema",
        action="store_true",
        help="restringe la salida al esquema JSON (format de Ollama)",
    )
    parser.add_argument("--alias", nargs="*", help="evalua solo estos alias (p. ej. D2 L3)")
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--salida", default=str(SALIDA))
    argumentos = parser.parse_args()
    load_dotenv()
    if argumentos.proveedor == "gemini":
        llm = GeminiDirecto(argumentos.max_tokens, argumentos.pausa)
    else:
        llm = OllamaDirecto(
            argumentos.host, argumentos.modelo, argumentos.max_tokens, argumentos.esquema
        )
    try:
        resultados = evaluar(llm, argumentos.tecnica, argumentos.limite, argumentos.alias)
    except (requests.RequestException, ErrorLLM) as error:
        sys.exit(f"Fallo de red o de Ollama: {error}")
    Path(argumentos.salida).write_text(
        json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(resultados["resumen"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
