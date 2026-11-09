from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .cache import CacheLocal
from .cliente import ClienteGitHub
from .errores import ErrorIngesta, ErrorLimiteTasa, ErrorRepositorioInvalido, ErrorRepositorioVacio
from .esquema import (
    Archivo,
    Comentario,
    Commit,
    DatosRepo,
    Issue,
    Limites,
    PullRequest,
    Revision,
)

_PATRON_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validar_repo(repo: str) -> str:
    if not _PATRON_REPO.match(repo or ""):
        raise ErrorRepositorioInvalido(f"identificador invalido (use propietario/repo): {repo!r}")
    return repo


def _login(usuario: dict | None) -> str | None:
    return (usuario or {}).get("login")


def _numero_de_url(url: str | None) -> int:
    try:
        return int((url or "").rstrip("/").rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return 0


def _commits(cliente: ClienteGitHub, repo: str, lim: Limites) -> tuple[Commit, ...]:
    params = {"since": lim.desde} if lim.desde else None
    try:
        resumenes = list(cliente.paginar(f"/repos/{repo}/commits", params, lim.max_commits))
    except ErrorRepositorioVacio:
        return ()
    resultado = []
    for r in resumenes:
        detalle = cliente.obtener(f"/repos/{repo}/commits/{r['sha']}")
        base = detalle.get("commit", {})
        resultado.append(
            Commit(
                sha=r["sha"],
                repo=repo,
                autor=_login(detalle.get("author")) or _login(r.get("author")),
                fecha=(base.get("author") or {}).get("date", ""),
                mensaje=base.get("message", ""),
                archivos=tuple(
                    Archivo(f["filename"], f.get("additions", 0), f.get("deletions", 0))
                    for f in detalle.get("files", [])
                ),
            )
        )
    return tuple(resultado)


def _pull_requests(cliente: ClienteGitHub, repo: str, lim: Limites):
    prs, revisiones = [], []
    params = {"state": "all", "sort": "updated", "direction": "desc"}
    for p in cliente.paginar(f"/repos/{repo}/pulls", params):
        if len(prs) >= lim.max_prs:
            break
        if lim.desde and p.get("created_at", "") < lim.desde:
            continue
        autor = _login(p.get("user"))
        prs.append(
            PullRequest(
                numero=p["number"],
                repo=repo,
                autor=autor,
                titulo=p.get("title", ""),
                estado=p.get("state", ""),
                creado=p.get("created_at", ""),
                fusionado=p.get("merged_at"),
            )
        )
        for r in cliente.paginar(f"/repos/{repo}/pulls/{p['number']}/reviews"):
            if not r.get("submitted_at"):
                continue  # revision pendiente (borrador), aun no emitida
            revisiones.append(
                Revision(
                    repo=repo,
                    pr_numero=p["number"],
                    pr_autor=autor,
                    revisor=_login(r.get("user")),
                    estado=r.get("state", ""),
                    fecha=r.get("submitted_at"),
                )
            )
    return tuple(prs), tuple(revisiones)


def _issues(cliente: ClienteGitHub, repo: str, lim: Limites) -> tuple[Issue, ...]:
    resultado = []
    params = {"state": "all", **({"since": lim.desde} if lim.desde else {})}
    for i in cliente.paginar(f"/repos/{repo}/issues", params):
        if "pull_request" in i:
            continue  # el listado mezcla PR; el limite cuenta solo issues reales
        if len(resultado) >= lim.max_issues:
            break
        resultado.append(
            Issue(
                numero=i["number"],
                repo=repo,
                autor=_login(i.get("user")),
                titulo=i.get("title", ""),
                estado=i.get("state", ""),
                creado=i.get("created_at", ""),
                asignados=tuple(a["login"] for a in i.get("assignees") or [] if a.get("login")),
            )
        )
    return tuple(resultado)


def _comentarios(cliente: ClienteGitHub, repo: str, lim: Limites) -> tuple[Comentario, ...]:
    resultado = []
    for ruta, origen, campo in (
        (f"/repos/{repo}/issues/comments", "issue", "issue_url"),
        (f"/repos/{repo}/pulls/comments", "revision", "pull_request_url"),
    ):
        params = {"since": lim.desde} if lim.desde else None
        for c in cliente.paginar(ruta, params, lim.max_comentarios):
            resultado.append(
                Comentario(
                    repo=repo,
                    numero=_numero_de_url(c.get(campo)),
                    autor=_login(c.get("user")),
                    fecha=c.get("created_at", ""),
                    origen=origen,
                )
            )
    return tuple(resultado)


def ingerir_repositorio(
    repo: str,
    cliente: ClienteGitHub,
    cache: CacheLocal,
    *,
    limites: Limites,
    refrescar: bool = False,
    ahora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[DatosRepo, bool]:
    """Devuelve (datos, desde_cache). Un fallo a mitad no deja nada en cache."""
    validar_repo(repo)
    if not refrescar:
        guardado = cache.cargar(repo)
        if guardado is not None and guardado.limites == limites:
            return guardado, True
    prs, revisiones = _pull_requests(cliente, repo, limites)
    datos = DatosRepo(
        repo=repo,
        obtenido=ahora().strftime("%Y-%m-%dT%H:%M:%SZ"),
        limites=limites,
        commits=_commits(cliente, repo, limites),
        pull_requests=prs,
        revisiones=revisiones,
        issues=_issues(cliente, repo, limites),
        comentarios=_comentarios(cliente, repo, limites),
    )
    cache.guardar(datos)
    return datos, False


@dataclass
class ResultadoIngesta:
    datos: dict[str, DatosRepo] = field(default_factory=dict)
    desde_cache: list[str] = field(default_factory=list)
    errores: dict[str, str] = field(default_factory=dict)
    pendientes: list[str] = field(default_factory=list)


def ingerir(
    repos: Iterable[str],
    cliente: ClienteGitHub,
    cache: CacheLocal,
    *,
    limites: Limites,
    refrescar: bool = False,
) -> ResultadoIngesta:
    """Ingesta varios repositorios; un error de repositorio no detiene a los demas.

    El limite de tasa si detiene la ejecucion: los repositorios restantes quedan pendientes.
    """
    resultado = ResultadoIngesta()
    lista = list(dict.fromkeys(repos))
    for posicion, repo in enumerate(lista):
        try:
            datos, en_cache = ingerir_repositorio(
                repo, cliente, cache, limites=limites, refrescar=refrescar
            )
        except ErrorLimiteTasa as exc:
            resultado.errores[repo] = str(exc)
            resultado.pendientes = lista[posicion + 1 :]
            break
        except ErrorIngesta as exc:
            resultado.errores[repo] = f"{type(exc).__name__}: {exc}"
            continue
        resultado.datos[repo] = datos
        if en_cache:
            resultado.desde_cache.append(repo)
    return resultado
