"""Indice vectorial de chunks de perfil sobre Chroma, con metadatos y reindexado incremental."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date

import chromadb
from chromadb.config import Settings
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

RUTA_POR_DEFECTO = "data/chroma"
COLECCION = "perfiles"
CLAVES_GRUPO = ("desarrollador", "repositorio", "tipo_fuente")
_LOTE = 64


def _aislar_sistema_efimero() -> None:
    """Da a cada cliente efimero su propio sistema de Chroma (ver `IndiceVectorial`)."""
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except ImportError:  # ruta interna de Chroma: si cambia en otra version, se omite el ajuste
        pass


@dataclass(frozen=True)
class ResultadoIndexado:
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    eliminados: int = 0


@dataclass(frozen=True)
class ResultadoConsulta:
    id: str
    texto: str
    metadatos: dict = field(default_factory=dict)
    distancia: float = 0.0


def _huella(texto: str, meta: dict) -> str:
    """Huella de texto y metadatos: un cambio de fechas sin cambio de texto tambien cuenta."""
    base = json.dumps([texto, meta], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _fecha_num(fecha: str | None) -> int | None:
    """'2026-03-05...' -> 20260305; None si no hay una fecha ISO valida."""
    try:
        d = date.fromisoformat((fecha or "")[:10])
    except ValueError:
        return None
    return d.year * 10000 + d.month * 100 + d.day


def _metadatos(doc: Document) -> dict:
    meta = {k: v for k, v in doc.metadata.items() if isinstance(v, (str, int, float, bool))}
    # Chroma solo compara numeros en $gte/$lte: las fechas ISO se duplican como AAAAMMDD.
    for origen, destino in (("fecha_desde", "desde_num"), ("fecha_hasta", "hasta_num")):
        n = _fecha_num(doc.metadata.get(origen))
        if n is not None:
            meta[destino] = n
    meta["huella"] = _huella(doc.page_content, meta)
    return meta


def _normalizar(chunk: Document, claves_grupo: tuple[str, ...]) -> Document:
    faltan = [k for k in ("id", *claves_grupo) if not chunk.metadata.get(k)]
    if faltan:
        raise ValueError(f"el chunk no tiene los metadatos obligatorios: {', '.join(faltan)}")
    meta = dict(chunk.metadata)
    if "desarrollador" in meta:
        meta["desarrollador"] = str(meta["desarrollador"]).casefold()
    return Document(page_content=chunk.page_content, metadata=meta)


def _donde(condiciones: list[dict]) -> dict | None:
    if not condiciones:
        return None
    return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}


class IndiceVectorial:
    """Coleccion Chroma de chunks. Sin `ruta` vive en memoria (pruebas); con ruta, persiste.

    Los embeddings los calcula `embeddings` (no Chroma), de modo que se reutiliza el modelo
    local del issue 6 y la consulta usa el mismo espacio vectorial. `claves_grupo` define los
    metadatos que identifican un grupo de chunks (por defecto los de los perfiles; la fuente
    interna usa otros), que es la unidad de sincronizacion de `indexar`.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        ruta: str | None = RUTA_POR_DEFECTO,
        coleccion: str = COLECCION,
        claves_grupo: tuple[str, ...] = CLAVES_GRUPO,
    ):
        if not claves_grupo:
            raise ValueError("se requiere al menos una clave de grupo")
        self._emb = embeddings
        self._claves = tuple(claves_grupo)
        ajustes = Settings(anonymized_telemetry=False)
        if ruta is None:
            # Los clientes efimeros comparten un sistema por proceso; con dos indices vivos, Chroma
            # 1.5 fallaba al azar ("Error finding id") en consultas con filtro. Vaciar la cache da
            # a cada indice su propio sistema (medido: 9 fallos en 600 construcciones a 0).
            _aislar_sistema_efimero()
            self._cliente = chromadb.EphemeralClient(settings=ajustes)
            coleccion = f"{coleccion}-{uuid.uuid4().hex}"
        else:
            self._cliente = chromadb.PersistentClient(path=ruta, settings=ajustes)
        self._col = self._cliente.get_or_create_collection(
            coleccion, configuration={"hnsw": {"space": "cosine"}}
        )

    def contar(self) -> int:
        return self._col.count()

    def indexar(self, chunks: list[Document]) -> ResultadoIndexado:
        """Sincroniza los grupos (desarrollador, repositorio, tipo_fuente) presentes en `chunks`.

        Idempotente: un chunk con el mismo id y el mismo texto no se vuelve a vectorizar; uno
        con el mismo id y texto distinto se actualiza; los chunks de un grupo que ya no
        existen en la entrada (p. ej. el documento se acorto) se eliminan. Los grupos que no
        aparecen en `chunks` no se tocan (para retirarlos, `eliminar`). El texto y los metadatos
        cuentan para detectar cambios.
        """
        chunks = [_normalizar(c, self._claves) for c in chunks]
        ids = [c.metadata["id"] for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("hay chunks con id repetido")
        por_grupo: dict[tuple, list[Document]] = {}
        for c in chunks:
            clave = tuple(c.metadata[k] for k in self._claves)
            por_grupo.setdefault(clave, []).append(c)

        nuevos = actualizados = sin_cambios = eliminados = 0
        for clave, docs in por_grupo.items():
            previos = self._col.get(
                where=_donde([{k: v} for k, v in zip(self._claves, clave)]),
                include=["metadatas"],
            )
            huellas = {i: m.get("huella") for i, m in zip(previos["ids"], previos["metadatas"])}
            pendientes = []
            for d in docs:
                meta = _metadatos(d)
                previa = huellas.get(d.metadata["id"])
                if previa == meta["huella"]:
                    sin_cambios += 1
                    continue
                pendientes.append((d, meta))
                if previa is None:
                    nuevos += 1
                else:
                    actualizados += 1
            for i in range(0, len(pendientes), _LOTE):
                lote = pendientes[i : i + _LOTE]
                textos = [d.page_content for d, _ in lote]
                self._col.upsert(
                    ids=[d.metadata["id"] for d, _ in lote],
                    documents=textos,
                    embeddings=self._emb.embed_documents(textos),
                    metadatas=[m for _, m in lote],
                )
            # Se borra al final: si el embedder falla antes, no se pierden los chunks previos.
            vigentes = {d.metadata["id"] for d in docs}
            obsoletos = [i for i in huellas if i not in vigentes]
            if obsoletos:
                self._col.delete(ids=obsoletos)
                eliminados += len(obsoletos)
        return ResultadoIndexado(nuevos, actualizados, sin_cambios, eliminados)

    def eliminar(
        self,
        *,
        desarrollador: str | None = None,
        repositorio: str | None = None,
        tipo_fuente: str | None = None,
    ) -> int:
        """Purga los chunks que coinciden con los filtros (al menos uno es obligatorio)."""
        condiciones = [
            {k: v}
            for k, v in (
                ("desarrollador", desarrollador.casefold() if desarrollador else None),
                ("repositorio", repositorio),
                ("tipo_fuente", tipo_fuente),
            )
            if v
        ]
        if not condiciones:
            raise ValueError("indica al menos un filtro para eliminar")
        ids = self._col.get(where=_donde(condiciones), include=[])["ids"]
        if ids:
            self._col.delete(ids=ids)
        return len(ids)

    def consultar(
        self,
        texto: str,
        k: int = 4,
        *,
        desarrollador: str | None = None,
        repositorio: str | None = None,
        tipo_fuente: str | None = None,
        desde: str | None = None,
        hasta: str | None = None,
        filtros: dict[str, str | int | float | bool] | None = None,
    ) -> list[ResultadoConsulta]:
        """Los k chunks mas cercanos a `texto`, filtrados por metadatos.

        `desarrollador` se compara sin distinguir mayusculas (el indice guarda el login en
        minusculas). `desde` y `hasta` (AAAA-MM-DD) seleccionan los chunks cuyo documento
        tiene actividad en ese rango; los documentos sin fechas se excluyen al filtrar por fecha.
        `filtros` agrega igualdades exactas sobre otros metadatos (p. ej. la categoria de un
        documento interno).
        """
        if k <= 0:
            raise ValueError("k debe ser positivo")
        condiciones: list[dict] = []
        if desarrollador:
            condiciones.append({"desarrollador": desarrollador.casefold()})
        if repositorio:
            condiciones.append({"repositorio": repositorio})
        if tipo_fuente:
            condiciones.append({"tipo_fuente": tipo_fuente})
        reservadas = set(filtros or {}) & {"desarrollador", "repositorio", "tipo_fuente"}
        if reservadas:
            raise ValueError(f"usa el parametro propio en lugar de filtros: {sorted(reservadas)}")
        condiciones.extend({clave: val} for clave, val in (filtros or {}).items())
        for valor, clave, op in ((desde, "hasta_num", "$gte"), (hasta, "desde_num", "$lte")):
            if valor:
                n = _fecha_num(valor)
                if n is None:
                    raise ValueError(f"fecha invalida (se espera AAAA-MM-DD): {valor!r}")
                condiciones.append({clave: {op: n}})
        if self._col.count() == 0:
            return []
        r = self._col.query(
            query_embeddings=[self._emb.embed_query(texto)],
            n_results=k,
            where=_donde(condiciones),
            include=["documents", "metadatas", "distances"],
        )
        return [
            ResultadoConsulta(i, t, m, d)
            for i, t, m, d in zip(
                r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0]
            )
        ]
