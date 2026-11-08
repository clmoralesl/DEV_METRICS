# Propuesta de caso organizacional: DevMetrics

ISY0101, Evaluación Parcial 1. Documento base de la evaluación.

Estado de la redacción: borrador. Los umbrales de la sección 4 y el texto de la sección 8 deben ser confirmados y reescritos por el equipo (la pauta exige que las justificaciones técnicas sean propias). Los puntos marcados como "por confirmar" no están verificados.

## 1. Organización

DevMetrics es una startup tecnológica del área de Recursos Humanos y Analítica TI. Su misión es optimizar la selección, evaluación y asignación de talento en equipos de desarrollo de software, transformando metadatos crudos de repositorios en perfiles de rendimiento claros y accionables.

## 2. Problema e impacto

Reclutadores técnicos y líderes de proyecto evalúan el estilo de trabajo de un desarrollador mediante revisión manual de currículums o métricas superficiales de código. Esto produce:

- Evaluación ineficiente: revisar manualmente commits, issues y pull requests (PR) consume muchas horas de los líderes técnicos.
- Clasificación errónea del talento: un perfil colaborativo se subestima si solo se mide el volumen de líneas de código, ignorando la resolución de incidentes o la documentación.
- Dificultad para cruzar requerimientos: no existe una herramienta interactiva para consultar qué desarrollador se ajusta mejor a un requerimiento técnico.

## 3. Solución propuesta

Un agente analítico basado en un Modelo de Lenguaje Grande (LLM) y Generación Aumentada por Recuperación (RAG, por Retrieval-Augmented Generation; Lewis et al., 2020), con tres componentes:

- Ingesta y vectorización: metadatos de la API de GitHub (commits, revisiones, issues, PR) convertidos en documentos indexados en una base vectorial.
- Perfilamiento por arquetipos: cada desarrollador recibe un perfil como mezcla de tres clases delimitadas: Druid (bases de datos, arquitectura, infraestructura), Cleric (soporte, revisión, resolución de bugs) y Bard (frontend, documentación, trabajo en equipo). La clase dominante es un resumen de la mezcla y solo se declara si supera a la segunda por un margen mínimo; en otro caso el perfil es mixto. Cada perfil incluye un nivel de confianza según el volumen de actividad, y con evidencia insuficiente el agente lo indica en lugar de forzar una clase. Así la herramienta sirve a desarrolladores de cualquier nivel de actividad, no solo a perfiles con mucho historial.
- Señales sin depender de convenciones de commits: rutas de archivos tocados, tipo de cambio de cada commit interpretado por el LLM a partir del mensaje y los archivos (no del prefijo), revisiones y comentarios en PR ajenos, issues atendidos, y volumen y diversidad de la actividad.
- Agente conversacional: el reclutador consulta en lenguaje natural y el LLM responde con una recomendación fundamentada en los perfiles recuperados y citando la evidencia de los repositorios.

## 4. Objetivos medibles

Metas definidas por el equipo para la versión inicial del agente.

| Id | Objetivo | Métrica | Meta propuesta | Método de medición |
| -- | -------- | ------- | -------------- | ------------------ |
| O1 | Identificar la clase dominante (evaluación piloto) | Exactitud (accuracy) de la clase dominante sobre 15 desarrolladores etiquetados, 5 por arquetipo | al menos 11 de 15 (73 %) | Etiquetado con criterios numéricos escritos antes de ver la salida del agente (sección 5), revisado a mano por los integrantes sobre una muestra; comparar con la salida del agente |
| O2 | Responder con rapidez | Tiempo de respuesta por consulta (mediana) | menos de 15 s | Registro de tiempos en un conjunto fijo de consultas |
| O3 | Fundamentar las respuestas | Tasa de respuestas con al menos una fuente recuperada citada | al menos 90 % | Revisión sobre un conjunto fijo de consultas |
| O4 | Evitar afirmaciones sin respaldo | Tasa de afirmaciones no sustentadas en el contexto recuperado | menos de 10 % | Revisión manual con rúbrica sobre una muestra |

| O5 | Ser honesto con poca evidencia | Proporción de casos de poca actividad en que el agente informa confianza baja o evidencia insuficiente | al menos 80 % de esos casos | Conjunto de al menos 4 desarrolladores con poca actividad (incluye a los integrantes), comparar el nivel de confianza informado con el volumen real |

Limitación: con 15 casos el resultado de O1 es indicativo, no estadísticamente concluyente, y O5 se mide sobre pocos casos.

## 5. Datos disponibles

- Fuente: repositorios públicos de GitHub, con logins reales de usuarios, obtenidos por la API REST de GitHub.
- Metadatos usados: historial de commits, revisiones de código, issues, PR y patrones de colaboración. No se usa el contenido privado ni datos fuera de lo público.
- Volumen (piloto): 15 desarrolladores con perfil marcado, 5 por arquetipo, con 2 a 3 repositorios públicos cada uno, más al menos 4 desarrolladores de poca actividad (incluidos los integrantes del equipo) para medir O5. Los 15 son perfiles públicos de profesionales, elegidos de forma dirigida (muestra no aleatoria).
- Etiquetas: no existen arquetipos previos. Los 15 con perfil marcado se etiquetan con reglas numéricas fijadas antes de evaluar al agente, sobre los últimos 30 commits del autor y sus revisiones de PR ajenos: Druid si al menos 70 % de los archivos tocados son de infraestructura o datos; Bard si al menos 60 % son documentación o frontend; Cleric si revisó al menos 400 PR ajenos y al menos 25 % de sus commits corrigen errores, identificados por el contenido del mensaje y no por un prefijo. Quien no cumple ninguna regla es un perfil mixto, fuera de los 15. Los casos de poca actividad no se etiquetan con estas reglas: se usan para medir O5.
- Limitaciones: las reglas usan señales parecidas a las que usa el agente, por lo que el resultado de O1 será optimista; la detección de correcciones por el contenido del mensaje es aproximada y su confiabilidad depende de lo descriptivo que sea cada autor.

## 6. Restricciones y normativas

- Datos públicos únicamente. Los Términos de Servicio de GitHub (2026) regulan el uso del contenido público; el uso de logins reales con fines de perfilamiento se limita a metadatos públicos y se revisará contra la Declaración de Privacidad de GitHub antes de publicar resultados.
- Privacidad: el sistema perfila personas identificables. Medidas propuestas: usar solo metadatos públicos, no inferir atributos sensibles, indicar que el arquetipo es una inferencia y no una evaluación laboral, no distribuir los datos recolectados en el repositorio y anonimizar los logins en el informe y la presentación.
- Límites de la API de GitHub: 60 solicitudes por hora sin autenticar y 5.000 por hora con token personal (GitHub, s. f.; cifras comprobadas con consultas a la API el 2026-11-04). Esto obliga a acotar la muestra y a guardar en caché las respuestas.
- Costo: se usa la capa gratuita de Gemini (Google AI Studio) como LLM principal y Ollama local como respaldo; embeddings locales. Los límites de la capa gratuita se consultan en Google AI Studio (Google, s. f.) y pueden cambiar; se registrarán al iniciar la implementación.
- Plazos: propuesta en semana 3, presentación en semana 6, entrega en semana 7.
- Uso de IA: declarado según la pauta. Una herramienta de IA apoyó la búsqueda y la preselección de la muestra y la redacción del borrador; las conclusiones y justificaciones son del equipo.

## 7. Alcance

Incluye ingesta, indexación, perfil como mezcla de tres arquetipos con nivel de confianza, agente conversacional con citas y evaluación con métricas. Excluye interfaz de producción, datos privados y uso en decisiones de contratación reales.

## 8. Motivación para agentes, LLM y RAG

- LLM: los metadatos son heterogéneos (texto de commits, issues, revisiones) y las consultas de los reclutadores son en lenguaje natural; un LLM interpreta ambos sin reglas manuales.
- RAG: los perfiles cambian con la actividad y no pueden quedar en los pesos del modelo; recuperar los datos al momento de la consulta mantiene la información actual y permite citar la evidencia (O3 y O4).
- Agente: la consulta requiere varios pasos (identificar el arquetipo pedido, recuperar perfiles, comparar candidatos y justificar), lo que se resuelve mejor con un agente que orquesta herramientas que con una sola llamada al modelo.

## 9. Referencias

- Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S. y Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *arXiv*. https://doi.org/10.48550/arXiv.2005.11401
- GitHub. (s. f.). *Rate limits for the REST API*. GitHub Docs. https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- GitHub. (2026). *GitHub Terms of Service*. https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
- Google. (s. f.). *Rate limits*. Google AI Studio. https://aistudio.google.com/docs/rate-limits
