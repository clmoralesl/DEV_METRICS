import json

import pytest
from github_falso import RespuestaFalsa, SesionFalsa, error_red

from devmetrics.ingesta import (
    CacheLocal,
    ClienteGitHub,
    ErrorAccesoDenegado,
    ErrorAutenticacion,
    ErrorLimiteTasa,
    ErrorNoEncontrado,
    ErrorRed,
    ErrorRepositorioInvalido,
    ErrorServidor,
    Limites,
    actividad_de,
    ingerir,
    ingerir_repositorio,
)

REPO = "acme/demo"
LIMITES = Limites(max_commits=50, max_prs=50, max_issues=50, max_comentarios=50)


def cliente_para(sesion, **kw):
    kw.setdefault("dormir", lambda s: None)
    return ClienteGitHub("token-de-prueba", session=sesion, **kw)


@pytest.fixture
def demo():
    sesion = SesionFalsa.desde_fixture("acme_demo.json")
    return sesion, cliente_para(sesion)


def test_paginacion_y_archivos_por_commit(demo, tmp_path):
    sesion, cliente = demo
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert [c.sha for c in datos.commits] == ["a1", "a2", "a3"]
    assert [a.ruta for a in datos.commits[0].archivos] == ["src/auth.py", "tests/test_auth.py"]
    assert datos.commits[0].archivos[0].adiciones == 5
    assert datos.commits[2].autor is None and datos.commits[2].archivos == ()


def test_normalizacion_de_pr_revisiones_issues_y_comentarios(demo, tmp_path):
    _, cliente = demo
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert [(p.numero, p.estado) for p in datos.pull_requests] == [(1, "closed"), (2, "open")]
    assert datos.pull_requests[0].fusionado is not None
    assert [(r.revisor, r.pr_autor, r.estado) for r in datos.revisiones] == [
        ("dev-beta", "dev-alfa", "APPROVED")
    ]
    assert [i.numero for i in datos.issues] == [3]
    assert datos.issues[0].asignados == ("dev-alfa",)
    assert sorted((c.origen, c.numero, c.autor) for c in datos.comentarios) == [
        ("issue", 3, "dev-alfa"),
        ("issue", 3, "dev-gamma"),
        ("revision", 1, "dev-beta"),
    ]


def test_limite_de_elementos_se_respeta(demo, tmp_path):
    _, cliente = demo
    lim = Limites(max_commits=2, max_prs=1, max_issues=50, max_comentarios=1)
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=lim)
    assert len(datos.commits) == 2
    assert len(datos.pull_requests) == 1
    assert len([c for c in datos.comentarios if c.origen == "issue"]) == 1


def test_segunda_ejecucion_usa_cache_sin_llamar_a_la_api(demo, tmp_path):
    sesion, cliente = demo
    cache = CacheLocal(tmp_path)
    primero, de_cache1 = ingerir_repositorio(REPO, cliente, cache, limites=LIMITES)
    llamadas = cliente.llamadas
    segundo, de_cache2 = ingerir_repositorio(REPO, cliente, cache, limites=LIMITES)
    assert (de_cache1, de_cache2) == (False, True)
    assert cliente.llamadas == llamadas
    assert segundo == primero


def test_refrescar_y_cambio_de_limites_vuelven_a_la_api(demo, tmp_path):
    _, cliente = demo
    cache = CacheLocal(tmp_path)
    ingerir_repositorio(REPO, cliente, cache, limites=LIMITES)
    _, c1 = ingerir_repositorio(REPO, cliente, cache, limites=LIMITES, refrescar=True)
    _, c2 = ingerir_repositorio(REPO, cliente, cache, limites=Limites(10, 10, 10, 10))
    assert (c1, c2) == (False, False)


def test_cache_corrupta_se_ignora(demo, tmp_path):
    _, cliente = demo
    cache = CacheLocal(tmp_path)
    cache.ruta(REPO).write_text("{no es json", encoding="utf-8")
    _, desde_cache = ingerir_repositorio(REPO, cliente, cache, limites=LIMITES)
    assert desde_cache is False
    assert json.loads(cache.ruta(REPO).read_text(encoding="utf-8"))["repo"] == REPO


def test_respuestas_vacias(tmp_path):
    vacias = {
        f"/repos/{REPO}/{ruta}": [[]]
        for ruta in ("commits", "pulls", "issues", "issues/comments", "pulls/comments")
    }
    datos, _ = ingerir_repositorio(
        REPO, cliente_para(SesionFalsa(vacias)), CacheLocal(tmp_path), limites=LIMITES
    )
    assert datos.commits == datos.pull_requests == datos.revisiones == ()
    assert datos.issues == datos.comentarios == ()


def test_repositorio_sin_commits_responde_409(tmp_path):
    rutas = {
        f"/repos/{REPO}/pulls": [[]],
        f"/repos/{REPO}/issues": [[]],
        f"/repos/{REPO}/issues/comments": [[]],
        f"/repos/{REPO}/pulls/comments": [[]],
        f"/repos/{REPO}/commits": [RespuestaFalsa(409, {"message": "Git Repository is empty."})],
    }
    datos, _ = ingerir_repositorio(
        REPO, cliente_para(SesionFalsa(rutas)), CacheLocal(tmp_path), limites=LIMITES
    )
    assert datos.commits == ()


def test_repositorio_inexistente_no_deja_cache_y_no_detiene_a_los_demas(demo, tmp_path):
    _, cliente = demo
    cache = CacheLocal(tmp_path)
    with pytest.raises(ErrorNoEncontrado):
        ingerir_repositorio("acme/no-existe", cliente, cache, limites=LIMITES)
    res = ingerir(["acme/no-existe", REPO], cliente, cache, limites=LIMITES)
    assert list(res.datos) == [REPO]
    assert "ErrorNoEncontrado" in res.errores["acme/no-existe"]
    assert cache.cargar("acme/no-existe") is None


@pytest.mark.parametrize("repo", ["", "sin-barra", "a/b/c", "a/ b", "../x/y"])
def test_identificador_invalido(demo, tmp_path, repo):
    _, cliente = demo
    with pytest.raises(ErrorRepositorioInvalido):
        ingerir_repositorio(repo, cliente, CacheLocal(tmp_path), limites=LIMITES)


def _con_commits_limitados(respuestas):
    sesion = SesionFalsa.desde_fixture("acme_demo.json")
    sesion.rutas[f"/repos/{REPO}/commits"] = respuestas
    return sesion


def test_limite_de_tasa_corto_espera_y_continua(tmp_path):
    esperas = []
    limite = RespuestaFalsa(
        403, {"message": "rate limit"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1002"}
    )
    ok = RespuestaFalsa(200, [{"sha": "a1", "author": {"login": "dev-alfa"}}])
    cliente = cliente_para(
        _con_commits_limitados([limite, ok]), dormir=esperas.append, ahora=lambda: 1000.0
    )
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert esperas == [3.0]
    assert [c.sha for c in datos.commits] == ["a1"]


def test_limite_de_tasa_largo_aborta_y_no_cachea(tmp_path):
    limite = RespuestaFalsa(
        403, {"message": "rate limit"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9000"}
    )
    cliente = cliente_para(_con_commits_limitados([limite]), ahora=lambda: 1000.0, max_espera=60)
    cache = CacheLocal(tmp_path)
    with pytest.raises(ErrorLimiteTasa) as exc:
        ingerir_repositorio(REPO, cliente, cache, limites=LIMITES)
    assert exc.value.espera > 60
    assert cache.cargar(REPO) is None


def test_limite_de_tasa_deja_pendientes_los_repositorios_restantes(tmp_path):
    limite = RespuestaFalsa(429, {"message": "slow down"}, {"Retry-After": "600"})
    cliente = cliente_para(_con_commits_limitados([limite]), max_espera=60)
    res = ingerir(
        [REPO, "acme/otro", "acme/tercero"], cliente, CacheLocal(tmp_path), limites=LIMITES
    )
    assert res.datos == {}
    assert REPO in res.errores
    assert res.pendientes == ["acme/otro", "acme/tercero"]


def test_403_que_no_es_limite_de_tasa(tmp_path):
    prohibido = RespuestaFalsa(403, {"message": "Repository access blocked"})
    cliente = cliente_para(_con_commits_limitados([prohibido]))
    with pytest.raises(ErrorAccesoDenegado):
        ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)


def test_token_invalido(tmp_path):
    cliente = cliente_para(_con_commits_limitados([RespuestaFalsa(401, {})]))
    with pytest.raises(ErrorAutenticacion):
        ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)


def test_error_de_servidor_se_reintenta_y_luego_se_informa(tmp_path):
    ok = RespuestaFalsa(200, [])
    sesion = _con_commits_limitados([RespuestaFalsa(502, {}), ok])
    datos, _ = ingerir_repositorio(
        REPO, cliente_para(sesion), CacheLocal(tmp_path), limites=LIMITES
    )
    assert datos.commits == ()

    sesion = _con_commits_limitados([RespuestaFalsa(503, {})])
    tmp_path = tmp_path / "otra"
    with pytest.raises(ErrorServidor):
        ingerir_repositorio(
            REPO, cliente_para(sesion, max_reintentos=2), CacheLocal(tmp_path), limites=LIMITES
        )
    assert sesion.pedidos.count(f"https://api.github.com/repos/{REPO}/commits") == 3


def test_red_caida_reintenta_acotado(tmp_path):
    sesion = SesionFalsa({f"/repos/{REPO}/pulls": error_red()})
    cliente = cliente_para(sesion, max_reintentos=2)
    with pytest.raises(ErrorRed):
        ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert cliente.llamadas == 3


def test_el_token_se_envia_como_bearer_y_sin_token_no_hay_cabecera():
    assert "Authorization" in cliente_para(SesionFalsa({}))._cabeceras
    assert "Authorization" not in ClienteGitHub(None, session=SesionFalsa({}))._cabeceras


def test_actividad_cuenta_solo_trabajo_ajeno(demo, tmp_path):
    _, cliente = demo
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    alfa = actividad_de("dev-alfa", [datos])
    beta = actividad_de("dev-beta", [datos])
    gamma = actividad_de("dev-gamma", [datos])
    assert len(alfa.commits) == 1 and alfa.commits[0].archivos == (
        "src/auth.py",
        "tests/test_auth.py",
    )
    assert (alfa.revisiones, alfa.comentarios, alfa.issues_atendidos) == (0, 1, 1)
    assert (beta.revisiones, beta.comentarios, beta.issues_atendidos) == (1, 1, 0)
    assert gamma.comentarios == 0


def test_limite_de_issues_cuenta_solo_issues_y_no_pr(tmp_path):
    sesion = SesionFalsa.desde_fixture("acme_demo.json")
    prs = [{"number": n, "pull_request": {}, "user": {"login": "x"}} for n in (10, 11, 12)]
    issue = {"number": 3, "user": {"login": "dev-gamma"}, "title": "t", "state": "open"}
    sesion.rutas[f"/repos/{REPO}/issues"] = [prs, [issue]]
    lim = Limites(50, 50, 1, 50)
    datos, _ = ingerir_repositorio(REPO, cliente_para(sesion), CacheLocal(tmp_path), limites=lim)
    assert [i.numero for i in datos.issues] == [3]


def test_no_pide_pagina_extra_al_alcanzar_el_limite(demo, tmp_path):
    sesion, cliente = demo
    list(cliente.paginar(f"/repos/{REPO}/commits", None, 2))
    assert sesion.pedidos == [f"https://api.github.com/repos/{REPO}/commits"]


def test_desde_acota_pr_issues_y_comentarios(demo, tmp_path):
    sesion, cliente = demo
    lim = Limites(50, 50, 50, 50, desde="2026-10-02T00:00:00Z")
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=lim)
    assert [p.numero for p in datos.pull_requests] == [2]


def test_revision_pendiente_no_se_cuenta(tmp_path):
    sesion = SesionFalsa.desde_fixture("acme_demo.json")
    sesion.rutas[f"/repos/{REPO}/pulls/1/reviews"] = [
        [{"user": {"login": "dev-beta"}, "state": "PENDING", "submitted_at": None}]
    ]
    datos, _ = ingerir_repositorio(
        REPO, cliente_para(sesion), CacheLocal(tmp_path), limites=LIMITES
    )
    assert datos.revisiones == ()


def test_retry_after_con_fecha_http_no_rompe(tmp_path):
    limite = RespuestaFalsa(429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    ok = RespuestaFalsa(200, [])
    esperas = []
    cliente = cliente_para(_con_commits_limitados([limite, ok]), dormir=esperas.append)
    ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert esperas == [60.0]


def test_clave_de_cache_sin_colisiones_ni_mayusculas(tmp_path):
    cache = CacheLocal(tmp_path)
    assert cache.ruta("a__b/c") != cache.ruta("a/b__c")
    assert cache.ruta("Foo/Bar") == cache.ruta("foo/bar")


def test_actividad_ignora_mayusculas_y_comentarios_de_recurso_desconocido(demo, tmp_path):
    _, cliente = demo
    datos, _ = ingerir_repositorio(REPO, cliente, CacheLocal(tmp_path), limites=LIMITES)
    assert len(actividad_de("DEV-Alfa", [datos]).commits) == 1
    from dataclasses import replace

    from devmetrics.ingesta.esquema import Comentario

    extra = Comentario(REPO, 999, "dev-alfa", "2026-10-04T00:00:00Z", "issue")
    con_extra = replace(datos, comentarios=datos.comentarios + (extra,))
    assert actividad_de("dev-alfa", [con_extra]).comentarios == 1
