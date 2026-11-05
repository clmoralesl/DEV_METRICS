# Plan de issues: DevMetrics

Repositorio: https://github.com/clmoralesl/DEV_METRICS
Base: pauta de la Evaluacion Parcial 1 (documentacion/contexto/pauta_resumen.md) y contenido de la unidad 1.1 (LLM y APIs), 1.2 (prompt engineering) y 1.3 (RAG, evaluacion con metricas y LangSmith).

## 1. Decisiones de base (propuestas, el equipo las confirma)

| Tema | Propuesta | Motivo |
| ---- | --------- | ------ |
| Lenguaje y framework | Python 3.13, LangChain | La unidad usa LangChain y los notebooks del curso estan en Python |
| LLM y embeddings | Chat: Google Gemini (capa gratuita de AI Studio) como principal y Ollama local como respaldo. Embeddings: modelo multilingue local (Ollama o sentence-transformers). Todo configurable por variables de entorno. GitHub Models, usado en el curso, fue retirado el 30 de julio de 2026 | Costo cero, embeddings sin limite de uso y sistema operativo aun sin red o sin cupo |
| Base vectorial | Chroma local | Los notebooks usan FAISS o Chroma; Chroma guarda metadatos y filtra, util para perfiles |
| Evaluacion | Metricas de la unidad (context precision, context recall, faithfulness, answer relevancy) con RAGAS o LangSmith | Es lo que la unidad pide para optimizar y respalda IE6 |
| Datos externos | GitHub REST API sobre repositorios open source publicos | IE3 exige fuentes externas |
| Datos internos | Base de conocimiento de la organizacion (requerimientos de proyectos, definicion de arquetipos, perfiles ya indexados) | IE3 exige fuentes internas |
| Interfaz | CLI conversacional con streaming; panel simple opcional | Prioriza lo evaluado: agente, RAG y evidencia |

Coherencia con IE3: el recuperador consulta (a) fuentes internas indexadas en Chroma y (b) la API de GitHub en vivo como herramienta del agente cuando el desarrollador no esta indexado o hay que refrescar su actividad.

## 2. Mapa rubrica a issues

| Indicador | Peso | Issues |
| --------- | ---- | ------ |
| IE1 Diseno del agente segun requerimientos | 15% | 1, 3, 4, 12, 13 |
| IE2 Prompts | 10% | 5, 13 |
| IE3 Flujos RAG con datos internos y externos | 10% | 6, 7, 8, 9, 10, 11 |
| IE4 Arquitectura (recuperacion, procesamiento, generacion) | 15% | 15 |
| IE5 Informe tecnico y repositorio | 10% | 2, 18, 19, 20 |
| IE6 Coherencia datos recuperados y respuestas | 10% | 16, 17, 21 |
| IE7 Diagrama de arquitectura (presentacion) | 10% | 15, 21 |
| IE8 Fundamentacion de decisiones | 10% | 17, 20, 21 |
| IE9 Lenguaje tecnico y evidencia | 10% | 16, 21 |

## 3. Issues

Convencion: una rama por issue, `<tipo>/<descripcion-en-espanol>-issue-<N>`, commits `tipo(alcance): descripcion (issue #N)`, PR con `Closes #N`. Tamano: S (menos de 2 h), M (2 a 5 h), L (mas de 5 h).

### Hito 0: Propuesta y base (semana 3)

#### #1 Completar la propuesta de caso para aprobacion del docente
Etiquetas: documentacion, hito-0. Tamano: M. Depende de: ninguno.
- Agregar a la propuesta actual: objetivos medibles (por ejemplo, precision del arquetipo sobre un conjunto etiquetado, tiempo de respuesta, tasa de respuestas con fuente), datos disponibles, restricciones (datos publicos, privacidad, limites de la API, costo), motivacion de agentes, LLM y RAG, y referencias.
- Criterio de aceptacion: el documento cubre los 7 elementos minimos de la pauta y el docente lo aprueba.

#### #2 Estructura del repositorio, entorno y verificacion automatica
Etiquetas: infraestructura, hito-0. Tamano: M. Depende de: ninguno.
- Estructura `src/devmetrics/`, `tests/`, `prompts/`, `data/`, `documentacion/`, `scripts/`; `pyproject.toml` con dependencias y ruff; `.env.example` sin valores; README esqueleto.
- Flujo de GitHub Actions que ejecuta lint y pruebas.
- Criterio de aceptacion: `scripts/verificar.ps1` en verde y la CI en verde sobre un repositorio recien clonado.

### Hito 1: Analisis y prompts (IE1, IE2)

#### #3 Analisis del caso y requisitos
Etiquetas: documentacion, hito-1. Tamano: M. Depende de: 1.
- `documentacion/analisis.md`: actores (reclutador, lider de proyecto), requisitos funcionales y no funcionales numerados, casos de uso, consultas tipo, y criterios de aceptacion medibles.
- Criterio de aceptacion: cada requisito se traza a una funcionalidad y a una prueba prevista.

#### #4 Modelo de arquetipos y senales de actividad
Etiquetas: dominio, hito-1. Tamano: M. Depende de: 3.
- Definir Druid, Cleric y Bard con senales observables: por ejemplo, proporcion de cambios en infraestructura y base de datos, revisiones de codigo y correccion de bugs, documentacion y frontend, colaboracion en PR.
- Funcion pura que calcula un puntaje por clase a partir de metadatos, con empates y datos insuficientes definidos.
- Criterio de aceptacion: pruebas unitarias de limites (sin actividad, una sola clase dominante, empate); servira como referencia para validar al LLM en el issue 13.

#### #5 Biblioteca de prompts versionada
Etiquetas: prompts, hito-1. Tamano: M. Depende de: 3.
- Prompts en `prompts/` con los cinco componentes de la unidad (rol, tarea, formato, restricciones, entrada): sistema, clasificacion de arquetipo y recomendacion con evidencia.
- Comparacion documentada de zero-shot, few-shot (3 a 5 ejemplos) y chain-of-thought sobre un mismo conjunto de casos, con tokens consumidos y consistencia de formato.
- Criterio de aceptacion: cada prompt tiene version, objetivo, resultados de validacion y salida estructurada comprobable por prueba.

### Hito 2: Pipeline RAG (IE3)

#### #6 Clientes de LLM (Gemini y Ollama) y embeddings locales
Etiquetas: rag, hito-2. Tamano: S. Depende de: 2.
- Interfaz unica sobre LangChain con dos proveedores de chat: Gemini (principal, clave en `.env`) y Ollama (respaldo local), seleccionables por variable de entorno; parametros (temperature, max_tokens), manejo de errores, limite de reintentos y mensajes claros ante falta de red, clave invalida o cupo agotado, con conmutacion al respaldo.
- Embeddings locales y multilingues; elegir el modelo con una prueba corta de recuperacion en espanol.
- Criterio de aceptacion: pruebas con cliente simulado, una prueba de integracion opcional por proveedor, README con los pasos para obtener la clave de AI Studio e instalar Ollama; ninguna clave en el repositorio.

#### #7 Ingesta externa desde la API de GitHub
Etiquetas: rag, hito-2. Tamano: L. Depende de: 2.
- Obtener commits, PR, revisiones e issues de repositorios publicos elegidos; paginacion, manejo de limite de tasa, cache local en `data/` y normalizacion a un esquema propio.
- Fixtures grabados para pruebas sin red.
- Criterio de aceptacion: ingesta reproducible por script; pruebas con respuestas vacias, repositorio inexistente y limite de tasa.

#### #8 Perfiles y chunking
Etiquetas: rag, hito-2. Tamano: M. Depende de: 7.
- Convertir la actividad en documentos de perfil por desarrollador y segmentarlos con RecursiveCharacterTextSplitter.
- Experimento de `chunk_size` y `chunk_overlap` con al menos tres configuraciones y su efecto en la recuperacion.
- Criterio de aceptacion: tabla comparativa de resultados guardada en `documentacion/pruebas.md` y configuracion elegida registrada en el codigo.

#### #9 Indexacion vectorial con metadatos
Etiquetas: rag, hito-2. Tamano: M. Depende de: 6, 8.
- Chroma con metadatos (desarrollador, repositorio, fecha, tipo de fuente); reindexado incremental sin duplicados.
- Criterio de aceptacion: consulta por similitud con filtros por metadatos y pruebas de idempotencia.

#### #10 Fuente interna: base de conocimiento de la organizacion
Etiquetas: rag, hito-2. Tamano: M. Depende de: 3, 9.
- Segunda coleccion con requerimientos de proyectos (por ejemplo, estabilizacion de microservicios), definicion de arquetipos y criterios de la empresa, redactados como documentos internos ficticios pero realistas.
- Criterio de aceptacion: una consulta del tipo "perfil adecuado para este proyecto" recupera el requerimiento y los perfiles relacionados.

#### #11 Recuperador combinado y herramienta de GitHub en vivo
Etiquetas: rag, hito-2. Tamano: L. Depende de: 7, 9, 10.
- Recuperador que combina fuentes internas y externas, con filtros de metadatos, k configurable y citas de origen en cada fragmento.
- Herramienta del agente que consulta la API en vivo cuando el desarrollador no esta indexado.
- Criterio de aceptacion: cada respuesta lista sus fuentes; pruebas de consulta sin resultados y con fuente externa caida.

### Hito 3: Agente (IE1, IE2, IE3)

#### #12 Cadena RAG y conversacion
Etiquetas: agente, hito-3. Tamano: M. Depende de: 5, 11.
- Prompt aumentado con contexto recuperado, respuesta de "evidencia insuficiente" cuando no hay soporte, y memoria de conversacion acotada a una ventana de N mensajes (las clases de memoria clasicas de LangChain pasaron a `langchain-classic`; usar el mecanismo vigente de la version instalada).
- Criterio de aceptacion: pruebas de pregunta sin contexto, pregunta ambigua y seguimiento de conversacion.

#### #13 Clasificacion por arquetipos con razonamiento
Etiquetas: agente, hito-3. Tamano: M. Depende de: 4, 5, 12.
- Clasificacion con chain-of-thought y salida estructurada validada; comparacion con el puntaje del issue 4 y registro de discrepancias.
- Criterio de aceptacion: conjunto etiquetado de al menos 15 desarrolladores y porcentaje de acuerdo reportado.

#### #14 Interfaz de consola con streaming
Etiquetas: interfaz, hito-3. Tamano: S. Depende de: 12.
- CLI conversacional con respuesta por streaming y comandos de ingesta e indexado.
- Criterio de aceptacion: demo reproducible desde el README.

### Hito 4: Arquitectura y evaluacion (IE4 a IE6)

#### #15 Arquitectura y diagramas
Etiquetas: documentacion, hito-4. Tamano: M. Depende de: 11.
- Diagrama de arquitectura (modulos de recuperacion, procesamiento y generacion), diagrama de flujo RAG y bocetos de dialogo.
- Criterio de aceptacion: diagrama en el repositorio y legible en una diapositiva.

#### #16 Conjunto de evaluacion y metricas
Etiquetas: evaluacion, hito-4. Tamano: L. Depende de: 12.
- 20 a 30 preguntas con perfil esperado y fuentes esperadas en `tests/casos_agente.json`.
- Script que calcula context precision, context recall, faithfulness y answer relevancy, y deja una tabla en `documentacion/pruebas.md`; trazas opcionales con LangSmith. Las metricas de generacion usan un LLM como juez: cachear respuestas y acotar el numero de preguntas segun el limite del proveedor elegido.
- Criterio de aceptacion: una sola orden regenera la tabla.

#### #17 Optimizacion y experimentos
Etiquetas: evaluacion, hito-4. Tamano: M. Depende de: 16.
- Variar k, chunking, modelo de embeddings y version de prompt; registrar el efecto en las metricas.
- Criterio de aceptacion: al menos cuatro experimentos con su tabla de resultados.

#### #18 Pruebas de software y evidencia
Etiquetas: pruebas, hito-4. Tamano: M. Depende de: 13.
- Cobertura de unidades, integracion con fixtures y casos limite; evidencia en `documentacion/pruebas.md`.
- Criterio de aceptacion: `scripts/verificar.ps1` en verde y la CI en verde.

### Hito 5: Entrega (semanas 6 y 7)

#### #19 README y scripts de ejecucion
Etiquetas: documentacion, hito-5. Tamano: M. Depende de: 14, 18.
- README con instalacion, variables de entorno, ejecucion, pruebas y evaluacion, probado desde cero en un equipo o carpeta limpia.
- Criterio de aceptacion: una persona ajena al proyecto lo ejecuta sin ayuda.

#### #20 Informe tecnico (maximo 5 paginas, APA)
Etiquetas: informe, hito-5. Tamano: L. Depende de: 15, 17, 19.
- Estructura segun IE1 a IE5, figuras, referencias APA y declaracion del uso de herramientas de IA.
- Criterio de aceptacion: entrega por AVA y correo, con el enlace al repositorio.

#### #21 Presentacion y defensa
Etiquetas: presentacion, hito-5. Tamano: M. Depende de: 16, 17, 20.
- 10 minutos de exposicion y 10 de preguntas: coherencia y resultados, defensa del diagrama, fundamentacion de decisiones, demo en vivo y demo grabada de respaldo; preguntas probables y respuestas ensayadas.
- Criterio de aceptacion: ensayo cronometrado con ambos integrantes participando.

## 4. Orden sugerido y ruta critica

1 y 2 en paralelo, luego 3, 4 y 5. Ruta critica tecnica: 7, 8, 9, 11, 12, 13, 16. Los issues 15 y 18 pueden avanzar en paralelo a 16. Plazos de la pauta: propuesta en semana 3, presentacion en semana 6, entrega en semana 7; el issue 1 es el primer bloqueo.
