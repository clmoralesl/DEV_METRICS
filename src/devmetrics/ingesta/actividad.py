from __future__ import annotations

from collections.abc import Iterable

from devmetrics.arquetipos.senales import Actividad
from devmetrics.arquetipos.senales import Commit as CommitSenal

from .esquema import DatosRepo


def _norm(login: str | None) -> str | None:
    return login.casefold() if login else None


def actividad_de(login: str, repos: Iterable[DatosRepo]) -> Actividad:
    """Convierte los datos normalizados en la entrada de calcular_senales para un login.

    GitHub no distingue mayusculas en los logins. Revisiones y comentarios cuentan solo sobre
    trabajo ajeno conocido: un comentario sobre un numero que no esta en los datos descargados
    no se cuenta, porque no se puede saber si el recurso era propio. Issues atendidos son los
    issues de otras personas asignados al login. Un commit sin cuenta vinculada (autor None) no
    se atribuye a nadie.
    """
    yo = _norm(login)
    commits, revisiones, comentarios, atendidos = [], 0, 0, 0
    for datos in repos:
        duenos = {p.numero: _norm(p.autor) for p in datos.pull_requests}
        duenos.update({i.numero: _norm(i.autor) for i in datos.issues})
        commits += [
            CommitSenal(c.mensaje, tuple(a.ruta for a in c.archivos), c.repo)
            for c in datos.commits
            if _norm(c.autor) == yo
        ]
        revisiones += sum(
            1 for r in datos.revisiones if _norm(r.revisor) == yo and _norm(r.pr_autor) != yo
        )
        comentarios += sum(
            1
            for c in datos.comentarios
            if _norm(c.autor) == yo and duenos.get(c.numero) not in (None, yo)
        )
        atendidos += sum(
            1
            for i in datos.issues
            if yo in {_norm(x) for x in i.asignados} and _norm(i.autor) != yo
        )
    return Actividad(tuple(commits), revisiones, comentarios, atendidos)
