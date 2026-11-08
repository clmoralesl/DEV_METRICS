# DevMetrics

Agente analitico basado en LLM y RAG que transforma metadatos de repositorios de GitHub (commits, revisiones, issues y pull requests) en perfiles de desarrolladores por arquetipos de trabajo, y permite consultarlos en lenguaje natural.

Proyecto de la asignatura ISY0101 Ingenieria de Soluciones con IA (Evaluacion Parcial 1).

## Estado

En planificacion. El trabajo se organiza por issues e hitos: https://github.com/clmoralesl/DEV_METRICS/issues

Las instrucciones de instalacion, ejecucion, pruebas y evaluacion se completaran en el issue #19.

## Requisitos

- Python 3.11 o superior
- Git

## Instalacion

```
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env        # Linux/macOS: cp .env.example .env
```

Completar en `.env` las claves indicadas en `.env.example` (nunca versionar `.env`).

## Verificacion

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verificar.ps1
```

Alternativa manual: `ruff check .` y `pytest`.

## Estructura de carpetas

- `src/devmetrics/`: codigo fuente del paquete
- `tests/`: pruebas automatizadas
- `prompts/`: plantillas de prompts
- `data/`: datos locales (no versionados, salvo `.gitkeep`)
- `documentacion/`: documentacion del proyecto
- `scripts/`: scripts de apoyo
- `.github/workflows/`: integracion continua

La ejecucion del agente, las pruebas y la evaluacion se completan en el issue #19.
