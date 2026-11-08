# Análisis del caso y requisitos: DevMetrics

ISY0101, Evaluación Parcial 1 (indicador IE1). Este documento deriva los requisitos del agente a partir de la propuesta de caso (`documentacion/propuesta_caso.md`) y del plan de issues (`documentacion/plan_issues.md`). Los umbrales numéricos (margen mínimo entre clases y volumen mínimo de actividad, citados en RF4, RF5, CA7 y CU4 como "a calibrar") se fijan en el issue 4 con datos de la muestra piloto; las demás metas provienen de los objetivos O1 a O5 de la propuesta.

## 1. Alcance y supuestos

- El sistema es un agente conversacional con RAG que perfila desarrolladores a partir de metadatos públicos de GitHub y responde consultas de selección y asignación de talento.
- El perfil de un desarrollador es una mezcla de tres arquetipos (Druid, Cleric, Bard) con puntajes que suman 1, una clase dominante opcional y un nivel de confianza. No se fuerza una clase cuando la evidencia es insuficiente.
- Fuera de alcance: interfaz de producción, datos privados, uso en decisiones de contratación reales.
- El arquetipo es una inferencia sobre actividad pública, no una evaluación laboral.

## 2. Actores

| Actor | Descripción | Necesidad principal |
| ----- | ----------- | ------------------- |
| A1 Reclutador técnico | Selecciona candidatos para vacantes | Saber rápido qué estilo de trabajo tiene un candidato y con qué evidencia |
| A2 Líder de proyecto | Asigna desarrolladores a proyectos existentes | Encontrar quién, dentro de la base de talento, se ajusta a un requerimiento técnico |
| A3 Desarrollador evaluado | Persona cuyo perfil se calcula (actor pasivo) | Que el perfil no la penalice por tener poca actividad pública ni por no seguir convenciones de commits |
| A4 Administrador de datos | Integrante del equipo que ejecuta ingesta e indexado | Reproducir la carga de datos y mantener la base de conocimiento interna |
| S1 API de GitHub | Sistema externo (fuente de metadatos) | Entregar commits, PR, revisiones e issues dentro de los límites de tasa |
| S2 Proveedor de LLM | Sistema externo (Gemini, con Ollama de respaldo) | Generar clasificaciones y respuestas |

## 3. Requisitos funcionales

Prioridad: E = esencial para la entrega, D = deseable (ningún requisito quedó como D en esta versión; se reserva para recortes si el plazo lo exige).

| Id | Requisito | Prioridad |
| -- | --------- | --------- |
| RF1 | El sistema obtiene de la API de GitHub los commits (con los archivos que toca cada uno), PR, revisiones e issues de repositorios públicos indicados, con paginación, manejo del límite de tasa y caché local | E |
| RF2 | El sistema normaliza los datos a un esquema propio y los guarda de forma reproducible | E |
| RF3 | El sistema calcula, para cada desarrollador, señales de actividad que no dependen de prefijos de commit: rutas de archivos tocados, tipo de cambio del commit, revisiones y comentarios en PR ajenos, issues atendidos, y volumen y diversidad de la actividad | E |
| RF4 | El sistema calcula una mezcla de arquetipos (puntajes por clase que suman 1), una clase dominante solo si supera a la segunda por un margen mínimo (en otro caso, "mixto") y un nivel de confianza según el volumen de actividad; margen y volumen mínimo a calibrar (issue 4) | E |
| RF5 | El sistema no fuerza una clase cuando la evidencia es insuficiente: informa confianza baja o "datos insuficientes" y lo explica, muestra la tendencia observada sin declarar clase dominante e indica qué actividad adicional permitiría un perfil más firme; umbral de volumen a calibrar (issue 4) | E |
| RF6 | El sistema clasifica el tipo de cambio de un commit (corrección, funcionalidad, documentación, infraestructura, refactor u otro) a partir del mensaje y los archivos, no del prefijo | E |
| RF7 | El sistema convierte la actividad en documentos de perfil, los segmenta y los indexa en una base vectorial con metadatos (desarrollador, repositorio, fecha, tipo de fuente, clase dominante, puntaje por clase y confianza), sin duplicados al reindexar, y reporta cuántos documentos agregó y cuántos ya existían | E |
| RF8 | El sistema mantiene una fuente interna indexada: requerimientos de proyectos, definición de arquetipos y criterios de la organización | E |
| RF9 | El sistema recupera fragmentos combinando fuentes internas y externas, con filtros por metadatos, k configurable y cita de origen en cada fragmento | E |
| RF10 | El agente consulta la API de GitHub en vivo cuando el desarrollador consultado no está indexado o se pide refrescar su actividad, y informa el error sin inventar datos si el login no existe | E |
| RF11 | El agente responde consultas en lenguaje natural con una recomendación fundamentada y lista las fuentes usadas | E |
| RF12 | El agente responde "evidencia insuficiente" cuando el contexto recuperado no sustenta la respuesta | E |
| RF13 | El agente mantiene el hilo de la conversación en una ventana acotada de N mensajes y resuelve preguntas de seguimiento | E |
| RF14 | El agente clasifica a un desarrollador con razonamiento, y devuelve una salida estructurada validada: mezcla por clase, clase dominante o "mixto", confianza y evidencias citadas | E |
| RF15 | El sistema compara la clasificación del LLM con la mezcla calculada por reglas (RF4) y registra las discrepancias (esencial: el issue 13 lo exige para validar al LLM) | E |
| RF16 | El agente permite comparar candidatos y ordenarlos según el ajuste a un requerimiento | E |
| RF17 | La interfaz de consola entrega la respuesta por streaming y ofrece comandos de ingesta e indexado | E |
| RF18 | Los proveedores de LLM y de embeddings se seleccionan por variables de entorno, con conmutación al respaldo ante falla del principal | E |
| RF19 | El sistema evalúa su desempeño con un conjunto fijo de casos y regenera la tabla de métricas con una sola orden | E |

## 4. Requisitos no funcionales

| Id | Requisito | Medida |
| -- | --------- | ------ |
| RNF1 | Rendimiento: tiempo de respuesta por consulta | Mediana menor a 15 s sobre el conjunto fijo de consultas (O2) |
| RNF2 | Trazabilidad: respuestas con fuente | Al menos 90 % de las respuestas citan al menos una fuente recuperada (O3) |
| RNF3 | Fidelidad: sin afirmaciones sin respaldo | Menos de 10 % de afirmaciones no sustentadas en el contexto, en revisión manual con rúbrica (O4) |
| RNF4 | Honestidad ante poca evidencia (necesidad de A3) | Al menos 80 % de los casos de poca actividad (mínimo 5) informan confianza baja o evidencia insuficiente (O5) |
| RNF5 | Exactitud del perfil | Al menos 11 de 15 desarrolladores etiquetados con la clase dominante correcta (O1); resultado indicativo por el tamaño de la muestra |
| RNF6 | Privacidad | Solo metadatos públicos; sin atributos sensibles inferidos; logins anonimizados en informe, presentación y en `tests/` (las pruebas versionadas usan alias o fixtures sintéticos); datos recolectados fuera del repositorio |
| RNF7 | Seguridad de credenciales | Ninguna clave en el repositorio; claves solo en `.env`, con `.env.example` sin valores |
| RNF8 | Robustez ante fallas externas | Mensajes claros ante falta de red, clave inválida, cupo agotado o repositorio inexistente; reintentos acotados; sin bucles |
| RNF9 | Reproducibilidad | Ingesta, indexado, pruebas y evaluación se ejecutan por script; el README permite ejecutar desde un clon limpio |
| RNF10 | Costo | Operación con la capa gratuita de Gemini y componentes locales; sin costo obligatorio |
| RNF11 | Mantenibilidad | Diccionario de rutas por arquetipo y umbrales configurables sin cambiar el código; prompts versionados |
| RNF12 | Calidad del código | `scripts/verificar.ps1` en verde (lint y pruebas) y CI en verde |

## 5. Casos de uso

### CU1 Consultar el perfil de un desarrollador
- Actor: A1 o A2.
- Precondición: el desarrollador está indexado, o es accesible por la API pública.
- Flujo principal: (1) el actor pide el perfil de un login; (2) el agente recupera los fragmentos del perfil; (3) responde con la mezcla de arquetipos, la clase dominante o "mixto", la confianza y las evidencias citadas.
- Alternativas: el login no está indexado, el agente lo consulta en vivo (RF10); el login no existe, informa el error sin inventar datos.
- Postcondición: el actor recibe un perfil con fuentes.

### CU2 Encontrar al mejor candidato para un requerimiento
- Actor: A2.
- Flujo principal: (1) el actor describe un proyecto o menciona uno de la base interna; (2) el agente recupera el requerimiento y los perfiles relacionados; (3) compara candidatos y recomienda con la evidencia de cada uno.
- Alternativa: ningún perfil tiene soporte suficiente, el agente responde "evidencia insuficiente" y dice qué falta.

### CU3 Filtrar candidatos por arquetipo
- Actor: A1 o A2.
- Flujo principal: el actor pide candidatos con un arquetipo dominante o alto en cierta clase; el agente aplica el filtro por metadatos y los lista con su confianza.
- Alternativa: no hay candidatos que cumplan, el agente lo informa y puede sugerir perfiles mixtos cercanos.

### CU4 Evaluar a un desarrollador de poca actividad
- Actor: A1 o A2, con A3 como sujeto evaluado (por ejemplo, quien estudia y trabaja, o contribuye de forma esporádica).
- Precondición: el desarrollador tiene pocos commits o pocas revisiones públicas, por debajo del mínimo de volumen a calibrar en el issue 4.
- Flujo principal: (1) el actor consulta el perfil; (2) el sistema calcula la mezcla con lo disponible; (3) el agente informa confianza baja o "datos insuficientes", muestra la tendencia observada sin declarar una clase dominante, y indica qué actividad adicional permitiría un perfil más firme.
- Postcondición: el perfil no se presenta como una clasificación firme ni penaliza a la persona por su bajo volumen.

### CU5 Hacer seguimiento en la conversación
- Actor: A1 o A2.
- Flujo principal: tras CU1 o CU2, el actor pregunta "¿y el segundo candidato?" o "compáralos"; el agente usa la ventana de conversación para resolver la referencia.
- Alternativa: la pregunta es ambigua, el agente pide precisar en lugar de suponer.

### CU6 Cargar e indexar datos
- Actor: A4.
- Flujo principal: (1) ejecuta el comando de ingesta con una lista de repositorios; (2) el sistema descarga, normaliza y guarda en caché; (3) ejecuta el indexado; (4) el sistema reporta cuántos documentos agregó y cuántos ya existían.
- Alternativas: límite de tasa alcanzado, el sistema espera o se detiene con un mensaje y conserva lo ya descargado; repositorio inexistente o vacío, se informa y se continúa con los demás.

### CU7 Evaluar el agente
- Actor: A4.
- Flujo principal: ejecuta una sola orden que corre el conjunto de casos y regenera la tabla de métricas (context precision, context recall, faithfulness, answer relevancy, y las métricas O1 a O5).

## 6. Consultas tipo

Conjunto semilla para el conjunto de evaluación del issue 16 (la lista final tendrá 20 a 30 consultas con perfil y fuentes esperadas).

| Id | Consulta | Caso de uso | Resultado esperado |
| -- | -------- | ----------- | ------------------ |
| Q1 | ¿Qué desarrollador con perfil Cleric tiene el mejor historial para un proyecto de estabilización de microservicios? | CU2 | Recomendación con candidatos Cleric, citando el requerimiento interno y los perfiles |
| Q2 | ¿Cuál es el perfil del desarrollador `<login>`? | CU1 | Mezcla de arquetipos, dominante o "mixto", confianza y evidencias |
| Q3 | Lista a los desarrolladores con mayor orientación Bard | CU3 | Lista ordenada con su confianza |
| Q4 | Necesito alguien para rediseñar el esquema de base de datos y la infraestructura, ¿a quién propones? | CU2 | Candidatos con puntaje alto en Druid |
| Q5 | Compara a `<login A>` y `<login B>` para un rol de revisión de código | CU2, CU5 | Comparación con evidencias de ambos |
| Q6 | ¿Qué estilo de trabajo tiene `<login poca actividad>`? | CU4 | Confianza baja o evidencia insuficiente, sin clase forzada |
| Q7 | ¿Y el segundo de la lista? (tras Q3) | CU5 | Resuelve la referencia con el historial |
| Q8 | ¿Quién es el mejor desarrollador Rust del equipo? (sin datos que lo sustenten) | CU2 | "Evidencia insuficiente" |
| Q9 | Perfil de un login que no existe | CU1 | Error informado, sin datos inventados |
| Q10 | Perfil de un desarrollador no indexado | CU1 | Consulta en vivo a GitHub y respuesta con fuente externa |

## 7. Criterios de aceptación medibles

| Id | Criterio | Medida | Origen |
| -- | -------- | ------ | ------ |
| CA1 | Exactitud de la clase dominante | Al menos 11 de 15 (73 %) en la muestra piloto de 15 desarrolladores etiquetados, 5 por arquetipo | O1, RNF5 |
| CA2 | Tiempo de respuesta | Mediana menor a 15 s en el conjunto fijo de consultas | O2, RNF1 |
| CA3 | Respuestas con fuente | Al menos 90 % citan una fuente recuperada | O3, RNF2 |
| CA4 | Afirmaciones sin respaldo | Menos de 10 % en la muestra revisada | O4, RNF3 |
| CA5 | Honestidad con poca evidencia | Al menos 80 % de al menos 5 desarrolladores de poca actividad (con 4 casos equivaldría a 4 de 4) con confianza baja o evidencia insuficiente, tendencia observada e indicación de qué falta | O5, RNF4 |
| CA6 | Salida estructurada válida | 100 % de las clasificaciones pasan la validación del esquema (mezcla suma 1, confianza presente, evidencias citadas) en el conjunto de prueba | RF14 |
| CA7 | Sin clase forzada (protege a A3) | En todo caso de prueba bajo el mínimo de volumen o con empate dentro del margen (umbrales a calibrar en el issue 4), la función de mezcla no declara clase dominante | RF4, RF5 |
| CA8 | Idempotencia del indexado | Reindexar los mismos datos no cambia el número de documentos | RF7 |
| CA9 | Reproducibilidad | Una orden regenera la tabla de métricas; el README permite ejecutar desde un clon limpio | RF19, RNF9 |
| CA10 | Calidad | `scripts/verificar.ps1` y la CI en verde | RNF12 |

## 8. Matriz de trazabilidad

Cada requisito se asigna a una funcionalidad (con su issue) y a una prueba prevista. Las pruebas automatizadas se ubican en `tests/`; las marcadas "manual" se registran en `documentacion/pruebas.md`.

### 8.1 Requisitos funcionales

| Requisito | Funcionalidad (issue) | Prueba prevista |
| --------- | --------------------- | --------------- |
| RF1 | Ingesta desde la API de GitHub (#7) | Pruebas con fixtures grabados: respuesta vacía, repositorio inexistente, límite de tasa, paginación |
| RF2 | Normalización a esquema propio y caché (#7) | Prueba de esquema sobre fixtures; la segunda ejecución no vuelve a llamar a la API |
| RF3 | Señales de actividad (#4) | Pruebas unitarias del cálculo de señales sobre commits sintéticos |
| RF4 | Función de mezcla, dominante y confianza (#4) | Pruebas de límites: sin actividad, poca actividad, una sola clase dominante, empate, mezcla; suma 1 |
| RF5 | Confianza y "datos insuficientes" en la mezcla (#4) y en el agente (#13) | Prueba unitaria bajo el umbral de volumen; el agente muestra tendencia e indica qué falta; casos de poca actividad en `tests/casos_agente.json` |
| RF6 | Prompt de tipo de cambio (#5) y su uso en el cálculo de señales (#4, #13) | Prueba de salida estructurada del prompt con respuesta simulada; casos con mensajes sin prefijo |
| RF7 | Perfiles, chunking e indexado (#8, #9) | Prueba de idempotencia, del reporte de agregados y existentes, y de filtros por metadatos (incluida clase dominante); experimento de chunking en `documentacion/pruebas.md` |
| RF8 | Fuente interna (#10) | Prueba: la consulta "perfil adecuado para este proyecto" recupera el requerimiento y perfiles relacionados |
| RF9 | Recuperador combinado (#11) | Pruebas de k, filtros y cita de origen; consulta sin resultados |
| RF10 | Herramienta de GitHub en vivo (#11) | Prueba con cliente simulado: desarrollador no indexado, login inexistente y fuente externa caída |
| RF11 | Cadena RAG (#12) | Prueba: cada respuesta incluye la lista de fuentes; conjunto de evaluación (#16) |
| RF12 | Respuesta "evidencia insuficiente" (#12) | Prueba de pregunta sin contexto (Q8) |
| RF13 | Memoria de conversación acotada (#12) | Pruebas de seguimiento (Q7), pregunta ambigua y recorte de la ventana |
| RF14 | Clasificación con razonamiento y salida validada (#13) | Prueba de validación del esquema con respuestas simuladas, válidas e inválidas |
| RF15 | Comparación contra la mezcla por reglas (#13) | Prueba: las discrepancias se registran en un caso con mezcla distinta |
| RF16 | Comparación de candidatos (#12, #13) | Consulta Q5 del conjunto de evaluación; revisión manual de la respuesta |
| RF17 | Consola con streaming (#14) | Prueba de comandos con LLM simulado; demo reproducible desde el README (manual) |
| RF18 | Clientes de LLM y embeddings (#6) | Pruebas con cliente simulado de selección por variable y de conmutación al respaldo; integración opcional por proveedor |
| RF19 | Conjunto de evaluación y métricas (#16) | Ejecución de la orden única; la tabla se regenera en `documentacion/pruebas.md` |

### 8.2 Requisitos no funcionales

| Requisito | Funcionalidad (issue) | Prueba prevista |
| --------- | --------------------- | --------------- |
| RNF1 | Evaluación (#16), optimización (#17) | Medición de tiempos en el conjunto fijo; mediana en `documentacion/pruebas.md` |
| RNF2 | Recuperador con citas (#11), cadena RAG (#12) | Conteo automático de respuestas con fuente en el conjunto de evaluación |
| RNF3 | Prompt de recomendación con restricciones (#5), cadena RAG (#12) | Métrica de faithfulness (#16) y revisión manual con rúbrica sobre una muestra |
| RNF4 | Confianza en el agente (#13) | Casos de poca actividad del conjunto de evaluación (#16), mínimo 4 |
| RNF5 | Clasificación (#13) | Acuerdo con las etiquetas de la muestra de 15 (#13, #16) |
| RNF6 | Ingesta y publicación (#7, #20) | Revisión manual de `data/` ignorado por Git y de logins anonimizados en informe y presentación; prueba automática que busca logins de la muestra en `tests/` y `documentacion/` |
| RNF7 | Estructura del repositorio (#2) | Verificación de `.gitignore` y de `.env.example`; búsqueda de claves antes de cada commit |
| RNF8 | Clientes (#6), ingesta (#7), herramienta en vivo (#11) | Pruebas de red caída, clave inválida, cupo agotado, reintentos acotados, repositorio inexistente y login inexistente (Q9) |
| RNF9 | README y scripts (#19) | Ejecución desde un clon limpio en un entorno virtual nuevo |
| RNF10 | Decisión de proveedores (#6) | Revisión manual: sin dependencias de pago obligatorias |
| RNF11 | Diccionario de rutas y umbrales (#4), prompts versionados (#5) | Prueba: cambiar el diccionario cambia la mezcla sin modificar código; validación de versión de cada prompt |
| RNF12 | Pruebas y CI (#2, #18) | `scripts/verificar.ps1` y la CI en verde |

### 8.3 Casos de uso y objetivos

| Elemento | Requisitos | Consultas / criterios |
| -------- | ---------- | --------------------- |
| CU1 | RF1, RF3, RF4, RF5, RF9, RF10, RF11, RF14 | Q2, Q9, Q10; CA1, CA3 |
| CU2 | RF4, RF5, RF8, RF9, RF11, RF12, RF16 | Q1, Q4, Q5, Q8; CA3, CA4 |
| CU3 | RF4, RF7, RF9 | Q3; CA3 |
| CU4 | RF3, RF4, RF5, RF14; RNF4 | Q6; CA5, CA7 |
| CU5 | RF13 | Q7 |
| CU6 | RF1, RF2, RF7 | CA8, CA9 |
| CU7 | RF19; RNF1, RNF4 | CA2 a CA5, CA9 |

## 9. Puntos abiertos

- El mínimo de volumen para declarar confianza suficiente y el margen mínimo entre la primera y la segunda clase se calibran en el issue 4 con la muestra piloto.
- El tamaño N de la ventana de conversación se fija en el issue 12.
- Las consultas Q1 a Q10 son semillas: al construir el conjunto de evaluación (issue 16) se usan alias en `tests/casos_agente.json`; la correspondencia con logins reales queda fuera del repositorio (`notas_equipo/`).
- Las prioridades E y D son propuestas del análisis y el equipo debe confirmarlas.
