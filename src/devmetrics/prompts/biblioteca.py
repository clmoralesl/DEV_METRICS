"""Carga y renderizado de los prompts versionados de la carpeta prompts/."""

from __future__ import annotations

import json
import re
import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from devmetrics.prompts.validadores import VALIDADORES

COMPONENTES = ("rol", "tarea", "formato", "restricciones", "entrada")
TECNICAS = ("zero_shot", "few_shot", "cot")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SALIDAS = ("json", "texto")
_NOMBRE = re.compile(r"^[a-z][a-z0-9_]*$")
_ETIQUETA = re.compile(r"<\s*/?\s*(\w+)\s*>", re.IGNORECASE)

# Supone una instalacion editable (src/devmetrics/prompts/ dentro del repositorio).
DIRECTORIO_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"


class ErrorPrompt(ValueError):
    """Prompt mal formado, inexistente o renderizado con variables incorrectas."""


@dataclass(frozen=True)
class Prompt:
    nombre: str
    version: str
    objetivo: str
    requisito: str
    salida: str
    componentes: dict[str, str]
    razonamiento: str = ""
    ejemplos: tuple[dict, ...] = ()
    validacion: dict = field(default_factory=dict)

    @property
    def variables(self) -> set[str]:
        return _campos(self.componentes["entrada"])

    def sistema(self, tecnica: str = "zero_shot") -> str:
        self._comprobar(tecnica)
        partes = [self.componentes[c] for c in ("rol", "restricciones", "formato")]
        if tecnica == "cot":
            partes.append(self.razonamiento)
        return "\n\n".join(p.strip() for p in partes if p.strip())

    def mensajes(self, variables: dict[str, str], tecnica: str = "zero_shot") -> list[dict]:
        """Lista de mensajes de chat (system, turnos de ejemplo y user final)."""
        self._comprobar(tecnica)
        mensajes = [{"role": "system", "content": self.sistema(tecnica)}]
        if tecnica == "few_shot":
            for ejemplo in self.ejemplos:
                mensajes.append({"role": "user", "content": self._usuario(ejemplo["variables"])})
                respuesta = json.dumps(ejemplo["salida"], ensure_ascii=False)
                mensajes.append({"role": "assistant", "content": respuesta})
        mensajes.append({"role": "user", "content": self._usuario(variables)})
        return mensajes

    def _comprobar(self, tecnica: str) -> None:
        if tecnica not in TECNICAS:
            raise ErrorPrompt(f"tecnica desconocida: {tecnica!r}; validas: {TECNICAS}")
        if tecnica == "cot" and not self.razonamiento:
            raise ErrorPrompt(f"el prompt {self.nombre!r} no define razonamiento para cot")
        if tecnica == "few_shot" and not self.ejemplos:
            raise ErrorPrompt(f"el prompt {self.nombre!r} no define ejemplos para few_shot")

    def _usuario(self, variables: dict[str, str]) -> str:
        esperadas = self.variables
        faltantes = esperadas - variables.keys()
        sobrantes = variables.keys() - esperadas
        if faltantes:
            raise ErrorPrompt(f"faltan variables en {self.nombre!r}: {sorted(faltantes)}")
        if sobrantes:
            raise ErrorPrompt(f"variables desconocidas en {self.nombre!r}: {sorted(sobrantes)}")
        if not all(isinstance(v, str) for v in variables.values()):
            raise ErrorPrompt(f"los valores de {self.nombre!r} deben ser texto")
        plantilla = self.componentes["entrada"].strip()
        delimitadores = {e.lower() for e in _ETIQUETA.findall(plantilla)}
        seguras = {k: _neutralizar(v, delimitadores) for k, v in variables.items()}
        entrada = plantilla.format(**seguras)
        return f"{self.componentes['tarea'].strip()}\n\n{entrada}"


def _neutralizar(valor: str, delimitadores: set[str]) -> str:
    """Evita que un dato cierre o abra los delimitadores del prompt (inyeccion)."""
    return _ETIQUETA.sub(
        lambda m: (
            f"[{m.group(0).strip('<> ').replace(' ', '')}]"
            if m.group(1).lower() in delimitadores
            else m.group(0)
        ),
        valor,
    )


def _campos(plantilla: str) -> set[str]:
    return {campo for _, campo, _, _ in string.Formatter().parse(plantilla) if campo}


def cargar(nombre: str, directorio: Path | str | None = None) -> Prompt:
    base = Path(directorio) if directorio else DIRECTORIO_PROMPTS
    if not _NOMBRE.match(nombre):
        raise ErrorPrompt(f"nombre de prompt invalido: {nombre!r}")
    ruta = base / f"{nombre}.toml"
    if not ruta.is_file():
        raise ErrorPrompt(f"no existe el prompt {nombre!r} en {base}")
    with ruta.open("rb") as archivo:
        try:
            datos = tomllib.load(archivo)
        except tomllib.TOMLDecodeError as error:
            raise ErrorPrompt(f"TOML invalido en {ruta.name}: {error}") from error
    return _construir(nombre, datos)


def listar(directorio: Path | str | None = None) -> list[str]:
    base = Path(directorio) if directorio else DIRECTORIO_PROMPTS
    return sorted(ruta.stem for ruta in base.glob("*.toml"))


def _construir(nombre: str, datos: dict) -> Prompt:
    if datos.get("nombre") != nombre:
        raise ErrorPrompt(f"el campo nombre ({datos.get('nombre')!r}) no coincide con {nombre!r}")
    version = datos.get("version", "")
    if not _VERSION.match(str(version)):
        raise ErrorPrompt(f"version invalida en {nombre!r}: {version!r} (se espera X.Y.Z)")
    for clave in ("objetivo", "requisito"):
        if not str(datos.get(clave, "")).strip():
            raise ErrorPrompt(f"falta {clave} en {nombre!r}")
    salida = datos.get("salida")
    if salida not in _SALIDAS:
        raise ErrorPrompt(f"salida invalida en {nombre!r}: {salida!r}; validas: {_SALIDAS}")
    if salida == "json" and nombre not in VALIDADORES:
        raise ErrorPrompt(f"el prompt {nombre!r} tiene salida json pero no validador")
    componentes = datos.get("componentes", {})
    vacios = [c for c in COMPONENTES if not str(componentes.get(c, "")).strip()]
    if vacios:
        raise ErrorPrompt(f"componentes ausentes o vacios en {nombre!r}: {vacios}")
    validacion = datos.get("validacion")
    if not isinstance(validacion, dict) or "estado" not in validacion:
        raise ErrorPrompt(f"falta la seccion validacion con estado en {nombre!r}")
    ejemplos = tuple(datos.get("ejemplos", ()))
    campos = _campos(componentes["entrada"])
    for ejemplo in ejemplos:
        if set(ejemplo.get("variables", {})) != campos or "salida" not in ejemplo:
            raise ErrorPrompt(f"ejemplo mal formado en {nombre!r}: debe traer {sorted(campos)}")
    return Prompt(
        nombre=nombre,
        version=version,
        objetivo=datos["objetivo"],
        requisito=datos["requisito"],
        salida=salida,
        componentes={c: componentes[c] for c in COMPONENTES},
        razonamiento=datos.get("tecnicas", {}).get("razonamiento", ""),
        ejemplos=ejemplos,
        validacion=validacion,
    )
