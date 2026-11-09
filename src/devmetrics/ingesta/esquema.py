from __future__ import annotations

from dataclasses import asdict, dataclass

VERSION_ESQUEMA = 1


@dataclass(frozen=True)
class Archivo:
    ruta: str
    adiciones: int = 0
    eliminaciones: int = 0


@dataclass(frozen=True)
class Commit:
    sha: str
    repo: str
    autor: str | None
    fecha: str
    mensaje: str
    archivos: tuple[Archivo, ...] = ()


@dataclass(frozen=True)
class PullRequest:
    numero: int
    repo: str
    autor: str | None
    titulo: str
    estado: str
    creado: str
    fusionado: str | None = None


@dataclass(frozen=True)
class Revision:
    repo: str
    pr_numero: int
    pr_autor: str | None
    revisor: str | None
    estado: str
    fecha: str | None


@dataclass(frozen=True)
class Issue:
    numero: int
    repo: str
    autor: str | None
    titulo: str
    estado: str
    creado: str
    asignados: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comentario:
    repo: str
    numero: int
    autor: str | None
    fecha: str
    origen: str  # "issue" (conversacion de issue o PR) o "revision" (comentario sobre el codigo)


@dataclass(frozen=True)
class Limites:
    max_commits: int
    max_prs: int
    max_issues: int
    max_comentarios: int
    desde: str | None = None


@dataclass(frozen=True)
class DatosRepo:
    repo: str
    obtenido: str
    limites: Limites
    commits: tuple[Commit, ...] = ()
    pull_requests: tuple[PullRequest, ...] = ()
    revisiones: tuple[Revision, ...] = ()
    issues: tuple[Issue, ...] = ()
    comentarios: tuple[Comentario, ...] = ()
    version: int = VERSION_ESQUEMA

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, d: dict) -> DatosRepo:
        if d.get("version") != VERSION_ESQUEMA:
            raise ValueError("version de esquema no compatible")
        return cls(
            repo=d["repo"],
            obtenido=d["obtenido"],
            limites=Limites(**d["limites"]),
            commits=tuple(
                Commit(**{**c, "archivos": tuple(Archivo(**a) for a in c["archivos"])})
                for c in d["commits"]
            ),
            pull_requests=tuple(PullRequest(**p) for p in d["pull_requests"]),
            revisiones=tuple(Revision(**r) for r in d["revisiones"]),
            issues=tuple(Issue(**{**i, "asignados": tuple(i["asignados"])}) for i in d["issues"]),
            comentarios=tuple(Comentario(**c) for c in d["comentarios"]),
        )
