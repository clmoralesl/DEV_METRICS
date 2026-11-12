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

## Consola conversacional (demo)

`scripts/consola.py` abre un chat con el agente (recuperacion sobre la base interna y los perfiles indexados, respuesta por streaming y fuentes citadas). Desde la raiz, con el entorno virtual activo:

```
python scripts/consola.py ingestar pallets/click --max-commits 50   # descarga a data/github (usa GITHUB_TOKEN si existe)
python scripts/consola.py indexar conocimiento                      # base interna (conocimiento/*.md)
python scripts/consola.py indexar perfiles                          # perfiles de lo descargado (opcional: --login <usuario>)
python scripts/consola.py chat --simulado                           # chat sin LLM ni red
python scripts/consola.py chat                                      # chat con el LLM real (Gemini, respaldo Ollama)
python scripts/consola.py chat --pregunta "que actividad tiene clmoralesl"   # una sola pregunta
```

- Sin clave y, tras la primera descarga del modelo de embeddings, sin red: `ingestar` solo se necesita si `data/github/` esta vacio (esta ignorado por Git: en un clon limpio, sin `indexar` el indice esta vacio y el agente responde "evidencia insuficiente"). `chat --simulado` usa los embeddings locales y un LLM simulado que lista los fragmentos recuperados con sus citas; no razona. Sirve para ver recuperacion, citas y streaming.
- Dentro del chat: `/ayuda`, `/desarrollador <login>` (filtra), `/reiniciar`, `/ingestar ...`, `/indexar [perfiles|conocimiento]`, `/salir`.
- `--repos propietario/repo ...` habilita la consulta en vivo a GitHub para desarrolladores no indexados.
- El streaming usa `.stream()` de LangChain (`ClienteLLM.flujo`): cambia al respaldo solo si el proveedor falla antes del primer trozo, y no reintenta.
- Por el streaming, el texto se muestra antes de validarlo: una cita que el modelo invente aparece en pantalla aunque no figure en la linea `Fuentes:` (solo lista las recuperadas). Si el proveedor se corta a mitad de la respuesta queda el texto parcial, un aviso de error y el turno no entra en la memoria.
- Con Ollama y un modelo de razonamiento (qwen3) el streaming puede llegar vacio (el razonamiento no es contenido): usar Gemini (`DEVMETRICS_LLM_PROVIDER=gemini`) para la demo.

## Evaluacion del agente

```
python scripts/evaluar_agente.py
```

Evalua las 24 preguntas de `tests/casos_agente.json` sobre un corpus sintetico (la base interna y
23 perfiles derivados de `tests/muestra_agregados.py` con alias neutros) y regenera la tabla de
`documentacion/pruebas.md` (seccion del issue 16) y `documentacion/evaluacion_resultados.json`.
Precision y recall de contexto son deterministas; fidelidad y relevancia usan el LLM como juez
(Gemini, `GOOGLE_API_KEY`) con cache en `data/evaluacion/`: repetir la orden no gasta cuota para lo ya
pedido. Opciones: `--limite N`, `--solo-recuperacion` (sin LLM ni clave), `--pausa S` (segundos entre
llamadas), `--proveedor ollama`, `--trazas` (LangSmith; requiere `LANGSMITH_API_KEY`). Si la cuota se
agota, el script guarda lo avanzado y se detiene sin reintentos.

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
- `documentacion/`: documentacion del proyecto (arquitectura y diagramas en `documentacion/arquitectura.md`)
- `scripts/`: scripts de apoyo
- `.github/workflows/`: integracion continua

La ejecucion del agente, las pruebas y la evaluacion se completan en el issue #19.
