"""Clasificacion por arquetipos con LLM: razonamiento, salida validada y comparacion con reglas."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Protocol

from devmetrics.arquetipos import CLASES, Configuracion, Perfil, Senales, calcular_perfil
from devmetrics.prompts import ErrorSalida, cargar, validadores

NOMBRE_PROMPT = "clasificacion_arquetipo"
NOMBRES = {clase: clase.capitalize() for clase in CLASES}
CONFIANZAS_BAJAS = ("baja", "datos_insuficientes")
_ID = re.compile(r"^\W*([A-Za-z]+\d+)\b")


class _LLM(Protocol):
    def invocar(self, mensajes: list[dict]) -> str: ...


@dataclass(frozen=True)
class Clasificacion:
    alias: str
    valida: bool
    mezcla: dict[str, float] | None
    dominante: str | None  # Druid | Cleric | Bard | mixto
    confianza: str | None
    evidencias: tuple[dict, ...]
    razonamiento: str
    faltante: str
    intentos: int
    errores: tuple[str, ...]
    guardia_aplicada: bool  # el perfil de reglas tenia datos insuficientes y se acoto la salida
    cumplia_guardia: bool | None  # la salida cruda ya cumplia la guardia (None si no aplica)
    perfil: Perfil
    discrepancia: dict = field(default_factory=dict)
    texto_crudo: str = ""  # ultima respuesta del LLM, para auditar fallos de formato
    correcciones: tuple[str, ...] = ()  # ajustes deterministas aplicados a la salida del LLM

    def a_dict(self) -> dict:
        datos = asdict(self)
        datos["perfil"] = self.perfil.a_dict()
        return datos


def evidencia_de_senales(
    senales: Senales, *, omitir_no_medidas: bool = False
) -> tuple[str, dict[str, str]]:
    """Renderiza las senales como lineas citables con identificador estable ([S1], [S2], ...).

    `omitir_no_medidas` descarta comentarios, issues y numero de repositorios, para fuentes (como
    la muestra agregada) que no los midieron: un cero inventado empuja a 'poca actividad'.
    """
    commits = f"{senales.n_commits} commits analizados"
    if not omitir_no_medidas:
        commits += f" en {senales.repos or 1} repositorio(s)"
    lineas = [commits, f"{senales.revisiones} revisiones de PR ajenos"]
    if not omitir_no_medidas:
        lineas += [
            f"{senales.comentarios} comentarios en PR e issues ajenos",
            f"{senales.issues_atendidos} issues atendidos",
        ]
    if senales.n_commits:
        porcentajes = {
            "infraestructura (CI, contenedores, migraciones)": senales.f_infraestructura,
            "documentacion": senales.f_documentacion,
            "frontend": senales.f_frontend,
            "pruebas": senales.f_pruebas,
            "codigo general": senales.f_codigo,
        }
        lineas += [
            f"{valor:.0%} de los archivos tocados son de {nombre}"
            for nombre, valor in porcentajes.items()
            if valor > 0
        ]
        lineas.append(f"{senales.f_correccion:.0%} de los commits corrigen errores")
    fuentes = {f"S{i}": texto for i, texto in enumerate(lineas, 1)}
    texto = "\n".join(f"[{i}] {linea}" for i, linea in fuentes.items())
    return texto, fuentes


def normalizar_fuentes(datos: dict, conocidas: set[str]) -> dict:
    """Reduce '[S1]' o 'S1 ' al identificador, para medir la clasificacion y no el formato."""
    evidencias = datos.get("evidencias")
    if not isinstance(evidencias, list):
        return datos
    for evidencia in evidencias:
        if isinstance(evidencia, dict) and isinstance(evidencia.get("fuente"), str):
            encontrada = _ID.match(evidencia["fuente"])
            if encontrada and encontrada.group(1).upper() in conocidas:
                evidencia["fuente"] = encontrada.group(1).upper()
    return datos


def comparar_con_reglas(clasificacion: Clasificacion, perfil: Perfil) -> dict:
    """Registro de discrepancias entre la clasificacion del LLM y el modelo del issue 4."""
    reglas = NOMBRES[perfil.dominante] if perfil.dominante else "mixto"
    registro = {
        "alias": clasificacion.alias,
        "dominante_llm": clasificacion.dominante,
        "dominante_reglas": reglas,
        "estado_reglas": perfil.estado,
        "difiere_dominante": clasificacion.dominante != reglas,
        "confianza_llm": clasificacion.confianza,
        "confianza_reglas": perfil.confianza,
        "max_diferencia_mezcla": None,
    }
    if clasificacion.mezcla:
        registro["max_diferencia_mezcla"] = round(
            max(abs(clasificacion.mezcla[NOMBRES[c]] - perfil.puntajes[c]) for c in CLASES), 3
        )
    return registro


def clasificar(
    alias: str,
    senales: Senales,
    llm: _LLM,
    config: Configuracion,
    *,
    tecnica: str = "cot",
    omitir_no_medidas: bool = False,
    contexto_extra: dict[str, str] | None = None,
) -> Clasificacion:
    """Clasifica con el LLM, valida la salida (una repeticion si falla) y compara con las reglas.

    `contexto_extra` agrega fuentes citables (p. ej. fragmentos recuperados) con su identificador.
    """
    perfil = calcular_perfil(senales, config)
    texto, fuentes = evidencia_de_senales(senales, omitir_no_medidas=omitir_no_medidas)
    fuentes = {**fuentes, **(contexto_extra or {})}
    if contexto_extra:
        texto += "\n" + "\n".join(f"[{i}] {t}" for i, t in contexto_extra.items())
    mensajes = cargar(NOMBRE_PROMPT).mensajes({"alias": alias, "evidencia": texto}, tecnica)

    errores: list[str] = []
    datos: dict | None = None
    crudo = ""
    correcciones: tuple[str, ...] = ()
    intentos = 0
    while datos is None and intentos < 2:
        intentos += 1
        crudo = llm.invocar(mensajes)
        try:
            datos, correcciones = _validar(crudo, set(fuentes), config)
        except ErrorSalida as error:
            errores = list(error.errores)
            mensajes = [
                *mensajes,
                {"role": "assistant", "content": crudo},
                {
                    "role": "user",
                    "content": "La respuesta no cumple el formato: "
                    + "; ".join(errores)
                    + ". Corrige y responde solo con el objeto JSON.",
                },
            ]

    if datos is None:
        guardia = perfil.estado == "datos_insuficientes"
        resultado = Clasificacion(
            alias=alias,
            valida=False,
            mezcla=None,
            dominante="mixto" if guardia else None,
            confianza="baja" if guardia else None,
            evidencias=(),
            razonamiento="",
            faltante=_faltante(perfil) if guardia else "",
            intentos=intentos,
            errores=tuple(errores),
            guardia_aplicada=guardia,
            cumplia_guardia=False if guardia else None,
            perfil=perfil,
            texto_crudo=crudo,
        )
    else:
        resultado = replace(
            _construir(alias, datos, perfil, intentos),
            texto_crudo=crudo,
            correcciones=correcciones,
        )
    return _con_discrepancia(resultado, perfil)


def _validar(crudo: str, fuentes: set[str], config: Configuracion) -> tuple[dict, tuple[str, ...]]:
    datos = normalizar_fuentes(validadores.extraer_json(crudo), fuentes)
    correcciones = _derivar(datos, config)
    validadores.validar_arquetipo(
        datos, margen_minimo=config.margen_minimo, fuentes_disponibles=fuentes
    )
    return datos, correcciones


def _derivar(datos: dict, config: Configuracion) -> tuple[str, ...]:
    """Normaliza la mezcla y deriva el dominante con la regla del margen (no se confia en el LLM).

    El LLM aporta la mezcla, la confianza y el razonamiento; la clase dominante es una
    consecuencia aritmetica de la mezcla, asi que se calcula en codigo. Cada ajuste se registra.
    """
    mezcla = datos.get("mezcla")
    if not (
        isinstance(mezcla, dict)
        and set(mezcla) == set(validadores.CLASES)
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in mezcla.values())
        and all(v >= 0 for v in mezcla.values())
        and sum(mezcla.values()) > 0
    ):
        return ()
    cambios = []
    total = sum(mezcla.values())
    if abs(total - 1) > validadores.TOLERANCIA_SUMA:
        datos["mezcla"] = mezcla = {k: round(v / total, 3) for k, v in mezcla.items()}
        cambios.append(f"mezcla renormalizada (sumaba {total:.3f})")
    if datos.get("confianza") not in validadores.CONFIANZAS:
        return tuple(cambios)
    ordenada = sorted(mezcla, key=mezcla.get, reverse=True)
    margen = mezcla[ordenada[0]] - mezcla[ordenada[1]]
    firme = margen >= config.margen_minimo - 1e-9 and datos["confianza"] not in CONFIANZAS_BAJAS
    derivado = ordenada[0] if firme else "mixto"
    if datos.get("dominante") != derivado:
        cambios.append(
            f"dominante derivado: el LLM dijo {datos.get('dominante')!r}, la regla da {derivado!r}"
        )
        datos["dominante"] = derivado
    return tuple(cambios)


def _faltante(perfil: Perfil) -> str:
    return f"faltan al menos {perfil.eventos_faltantes} eventos de actividad para un perfil firme"


def _construir(alias: str, datos: dict, perfil: Perfil, intentos: int) -> Clasificacion:
    dominante, confianza = datos["dominante"], datos["confianza"]
    faltante = datos.get("faltante", "") or ""
    guardia = perfil.estado == "datos_insuficientes"
    cumplia = None
    if guardia:
        cumplia = dominante == "mixto" and confianza in CONFIANZAS_BAJAS
        dominante = "mixto"
        confianza = confianza if confianza in CONFIANZAS_BAJAS else "baja"
        faltante = faltante or _faltante(perfil)
    return Clasificacion(
        alias=alias,
        valida=True,
        mezcla=dict(datos["mezcla"]),
        dominante=dominante,
        confianza=confianza,
        evidencias=tuple(datos["evidencias"]),
        razonamiento=datos.get("razonamiento", "") or "",
        faltante=faltante,
        intentos=intentos,
        errores=(),
        guardia_aplicada=guardia,
        cumplia_guardia=cumplia,
        perfil=perfil,
    )


def _con_discrepancia(resultado: Clasificacion, perfil: Perfil) -> Clasificacion:
    return replace(resultado, discrepancia=comparar_con_reglas(resultado, perfil))


__all__ = [
    "Clasificacion",
    "NOMBRES",
    "clasificar",
    "comparar_con_reglas",
    "evidencia_de_senales",
    "normalizar_fuentes",
]
