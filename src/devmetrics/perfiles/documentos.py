"""Documentos de perfil por desarrollador, repositorio y tipo de fuente.

Cada documento es un registro de actividad de una linea por evento, con metadatos escalares
(compatibles con filtros de bases vectoriales) para la indexacion del issue 9.
"""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.documents import Document

from devmetrics.ingesta.esquema import DatosRepo

TIPOS_FUENTE = ("commits", "pull_requests", "revisiones", "issues")
MAX_ARCHIVOS = 4
MAX_ASUNTO = 200


def _norm(login: str | None) -> str | None:
    return login.casefold() if login else None


def _dia(fecha: str | None) -> str:
    return (fecha or "")[:10]


def _asunto(texto: str) -> str:
    lineas = texto.strip().splitlines()
    return (lineas[0].strip() if lineas else "")[:MAX_ASUNTO]


def _archivos(rutas: list[str]) -> str:
    if not rutas:
        return ""
    visibles = ", ".join(rutas[:MAX_ARCHIVOS])
    resto = len(rutas) - MAX_ARCHIVOS
    return f" [archivos: {visibles}{f', +{resto} mas' if resto > 0 else ''}]"


def _documento(login: str, repo: str, tipo: str, eventos: list[tuple[str, str]]) -> Document | None:
    """eventos: pares (fecha, linea). Devuelve None si no hay eventos."""
    if not eventos:
        return None
    eventos = sorted(eventos)
    fechas = [f for f, _ in eventos if f]
    cabecera = f"Actividad de {login} en {repo} ({tipo.replace('_', ' ')})"
    return Document(
        page_content="\n".join([cabecera, *(linea for _, linea in eventos)]),
        metadata={
            "desarrollador": login,
            "repositorio": repo,
            "tipo_fuente": tipo,
            "fecha_desde": fechas[0] if fechas else "",
            "fecha_hasta": fechas[-1] if fechas else "",
            "n_eventos": len(eventos),
        },
    )


def documentos_de(login: str, repos: Iterable[DatosRepo]) -> list[Document]:
    """Documentos de perfil de un login, uno por repositorio y tipo de fuente con eventos.

    Misma atribucion que actividad_de: logins sin distinguir mayusculas, revisiones solo sobre
    PR ajenos. Los comentarios no se documentan porque el esquema no guarda su texto.
    """
    yo = _norm(login)
    nombre = login.casefold()
    docs: list[Document] = []
    for datos in repos:
        por_tipo: dict[str, list[tuple[str, str]]] = {t: [] for t in TIPOS_FUENTE}
        for c in datos.commits:
            if _norm(c.autor) == yo:
                dia = _dia(c.fecha)
                linea = f"[{dia}] commit {c.sha[:7]}: {_asunto(c.mensaje)}"
                por_tipo["commits"].append((dia, linea + _archivos([a.ruta for a in c.archivos])))
        for p in datos.pull_requests:
            if _norm(p.autor) == yo:
                dia = _dia(p.creado)
                por_tipo["pull_requests"].append(
                    (dia, f"[{dia}] pull request #{p.numero} ({p.estado}): {_asunto(p.titulo)}")
                )
        for r in datos.revisiones:
            if _norm(r.revisor) == yo and _norm(r.pr_autor) != yo:
                dia = _dia(r.fecha)
                por_tipo["revisiones"].append(
                    (
                        dia,
                        f"[{dia}] reviso el PR #{r.pr_numero} de otra persona: {r.estado}",
                    )
                )
        for i in datos.issues:
            if _norm(i.autor) == yo:
                dia = _dia(i.creado)
                por_tipo["issues"].append(
                    (dia, f"[{dia}] abrio el issue #{i.numero} ({i.estado}): {_asunto(i.titulo)}")
                )
            elif yo in {_norm(x) for x in i.asignados}:
                dia = _dia(i.creado)
                por_tipo["issues"].append(
                    (dia, f"[{dia}] atendio el issue #{i.numero} ({i.estado}): {_asunto(i.titulo)}")
                )
        for tipo in TIPOS_FUENTE:
            doc = _documento(nombre, datos.repo, tipo, por_tipo[tipo])
            if doc is not None:
                docs.append(doc)
    return docs
