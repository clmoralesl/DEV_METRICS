"""Agregados de la muestra piloto con alias (RNF6: sin logins reales).

Cada fila: alias -> (clase esperada, infra, docs+frontend, pruebas, fix, revisiones), con
porcentajes de archivos tocados como fracciones. Los valores son agregados medidos sobre 20 a 30
commits recientes; las filas con datos de archivos desconocidos se registran como codigo general
y las de fix desconocido como 0. La correspondencia alias-login esta en notas_equipo/.
"""

from devmetrics.arquetipos import Senales

# alias: (esperada, infra, docs_front, pruebas, fix, revisiones, commits)
POSITIVOS = {
    "D1": ("druid", 0.96, 0.01, 0.0, 0.17, 9, 30),
    "D2": ("druid", 0.78, 0.07, 0.0, 0.37, 2, 30),
    "D3": ("druid", 0.79, 0.03, 0.0, 0.03, 79, 30),
    "D4": ("druid", 0.98, 0.0, 0.0, 0.0, 7, 20),
    "D5": ("druid", 0.90, 0.0, 0.0, 0.65, 94, 20),
    "B1": ("bard", 0.0, 0.76, 0.0, 0.37, 1, 30),
    "B2": ("bard", 0.0, 0.85, 0.0, 0.37, 296, 30),
    "B3": ("bard", 0.14, 0.67, 0.0, 0.47, 102, 30),
    "B4": ("bard", 0.0, 1.0, 0.0, 0.0, 4503, 20),
    "B5": ("bard", 0.0, 0.77, 0.0, 0.0, 333, 20),
    "C1": ("cleric", 0.13, 0.12, 0.42, 0.70, 1170, 30),
    "C2": ("cleric", 0.25, 0.31, 0.18, 0.30, 583, 30),
    "C3": ("cleric", 0.04, 0.42, 0.08, 0.40, 1136, 30),
    "C4": ("cleric", 0.0, 0.0, 0.0, 0.30, 943, 20),
    "C5": ("cleric", 0.0, 0.0, 0.0, 0.35, 883, 20),
}

# Perfiles que las reglas de etiquetado no asignaron a ninguna clase (mixtos esperados).
MIXTOS = {
    "M1": ("mixto", 0.0, 0.28, 0.0, 0.10, 462, 30),
    "M2": ("mixto", 0.38, 0.47, 0.0, 0.0, 119, 30),
    "M3": ("mixto", 0.0, 0.33, 0.0, 0.0, 0, 20),
    "M4": ("mixto", 0.80, 0.0, 0.0, 0.45, 825, 30),
}


# Poca actividad (volumen < minimo_eventos = 10). SINTETICOS: ilustran el caso, no son medidos.
# La clase esperada es "mixto" con confianza baja o datos insuficientes.
POCA_ACTIVIDAD = {
    "L1": ("mixto", 0.50, 0.0, 0.0, 0.25, 0, 4),
    "L2": ("mixto", 0.0, 1.0, 0.0, 0.0, 1, 3),
    "L3": ("mixto", 0.0, 0.0, 0.0, 0.50, 2, 6),
    "L4": ("mixto", 0.0, 0.0, 0.0, 0.0, 0, 2),
}


def senales(fila: tuple) -> Senales:
    _, infra, docs_front, pruebas, fix, revisiones, commits = fila
    return Senales(
        n_commits=commits,
        f_infraestructura=infra,
        f_documentacion=docs_front,
        f_pruebas=pruebas,
        f_codigo=max(0.0, 1.0 - infra - docs_front - pruebas),
        f_correccion=fix,
        revisiones=revisiones,
    )
