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

## Modelos de lenguaje y embeddings

El paquete `devmetrics.llm` ofrece una interfaz unica (`ClienteLLM`) sobre LangChain con dos proveedores: Gemini (principal) y Ollama (respaldo local). Ante red caida, clave invalida o cupo agotado, reintenta con espera creciente (maximo 2 reintentos) y conmuta al respaldo; si ambos fallan, informa la causa de cada uno.

### Clave de Google AI Studio (Gemini)

1. Entrar a https://aistudio.google.com/apikey con una cuenta Google y crear una clave (la capa gratuita basta).
2. Copiarla en `.env` como `GOOGLE_API_KEY=...`. El archivo `.env` esta ignorado por Git; nunca subir la clave.

### Ollama (respaldo local)

1. Instalar desde https://ollama.com/download (Windows: `OllamaSetup.exe`).
2. Descargar un modelo pequeno: `ollama pull qwen3:0.6b`.
3. Si Ollama corre en otra direccion, definir `OLLAMA_HOST` en `.env`.

### Seleccion por variables de entorno (todas opcionales)

- `DEVMETRICS_LLM_PROVIDER`: `gemini` (por defecto) u `ollama`.
- `DEVMETRICS_LLM_FALLBACK`: `ollama` (por defecto), `gemini` o `none`.
- `DEVMETRICS_GEMINI_MODEL` (por defecto `gemini-3.5-flash-lite`) y `DEVMETRICS_OLLAMA_MODEL` (por defecto `qwen3:0.6b`).
- `DEVMETRICS_LLM_TEMPERATURE` (0.0), `DEVMETRICS_LLM_MAX_TOKENS` (1024) y `DEVMETRICS_LLM_MAX_RETRIES` (2).
- Un 429 se trata como cupo agotado: no se reintenta y se conmuta al respaldo (no distingue el limite por minuto del diario). Las respuestas vacias tambien conmutan.

```python
from devmetrics.llm import ClienteLLM
print(ClienteLLM().invocar("Responde solo: listo"))
```

### Embeddings locales

`ModeloEmbeddings` usa `paraphrase-multilingual-MiniLM-L12-v2` mediante fastembed (ONNX, sin torch). La primera llamada descarga el modelo (unos 220 MB) a la cache local. Usa el almacen de certificados del sistema (`truststore`), necesario si un antivirus o proxy inspecciona HTTPS.

### Pruebas de integracion (opcionales)

Se omiten por defecto. Para ejecutarlas, con la clave, Ollama y el modelo listos:

```
set DEVMETRICS_INTEGRACION=1
set DEVMETRICS_OLLAMA_MODEL=qwen3:0.6b
python -m pytest tests/test_llm_integracion.py -rs
```

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
