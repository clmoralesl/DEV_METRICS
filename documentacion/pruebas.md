# Evidencia de pruebas

## Experimento de chunking (issue 8, IE3)

Objetivo: elegir `chunk_size` y `chunk_overlap` para segmentar los documentos de perfil con
`RecursiveCharacterTextSplitter` y medir su efecto en la recuperacion.

### Procedimiento

- Datos: 400 commits de `pallets/click` ingeridos con `scripts/ingestar.py` (directorio
  `data/github_chunking/`, ignorado por Git). Cinco desarrolladores con mas commits, sin bots.
- Documentos: `devmetrics.perfiles.documentos_de`, solo la fuente `commits`, una linea por
  commit con fecha, sha corto, asunto y hasta cuatro archivos.
- Recuperacion: embeddings locales (`ModeloEmbeddings`, MiniLM multilingue), similitud coseno
  en memoria, filtro por desarrollador y `k = 4` chunks por consulta.
- Consultas: una por tipo de cambio (correccion, funcionalidad, documentacion, refactor).
- Relevancia: tipo asignado por `arquetipos.clasificar_cambio` (heuristica independiente del
  embedding). Se evaluan los pares desarrollador x tipo con al menos 3 commits del tipo.
- Metricas: precision (parte de los commits recuperados que son del tipo consultado),
  cobertura (parte de los commits del tipo que aparecen en lo recuperado), F1 y contexto
  (caracteres recuperados, costo en el prompt).
- Reproduccion (2026-11-09, `pallets/click`, 400 commits mas recientes a esa fecha; la cache
  fija el resultado, por lo que otra fecha de ingesta puede dar cifras distintas):

  ```
  python scripts/ingestar.py pallets/click --data-dir data/github_chunking --max-commits 400 --max-prs 30 --max-issues 30 --max-comentarios 50
  python scripts/experimento_chunking.py --repo pallets/click
  ```

  El script toma los 5 desarrolladores con mas commits de la cache y no imprime sus logins.

### Resultados (9 pares evaluados)

| chunk_size | chunk_overlap | chunks | caracteres/chunk | precision | cobertura | F1 | contexto |
|---|---|---|---|---|---|---|---|
| 300 | 30 | 247 | 210 | 0.431 | 0.225 | 0.296 | 813 |
| 600 | 0 | 103 | 505 | 0.320 | 0.410 | 0.360 | 1951 |
| 600 | 120 | 108 | 510 | 0.375 | 0.456 | 0.411 | 2009 |
| 1000 | 100 | 60 | 875 | 0.241 | 0.451 | 0.314 | 3135 |
| 2000 | 200 | 31 | 1791 | 0.243 | 0.629 | 0.351 | 6125 |

### Configuracion elegida

`chunk_size = 600`, `chunk_overlap = 120` (`devmetrics.perfiles.chunking.CONFIG_CHUNKING`).
Tiene el mejor F1 y un contexto de unos 2000 caracteres. Chunks pequenos (300) son precisos
pero recuperan poca parte de la actividad; chunks grandes (1000 y 2000) mezclan tipos de
cambio en un mismo chunk y bajan la precision, y 2000 cuesta tres veces mas contexto. A igual
tamano, 600 con solapamiento de 120 supera a 600 sin solapar en precision y cobertura, pero con
9 pares y sin medida de dispersion es una tendencia, no una diferencia comprobada.

### Limites

- Un solo repositorio, una sola fuente (commits) y 9 pares: las diferencias pequenas
  (p. ej. 1000 frente a 2000) no son concluyentes; la tendencia general si.
- La relevancia depende de la heuristica de tipo de cambio, no de juicio humano.
- `k` fijo: la cobertura crece con el tamano del chunk en parte porque se recupera mas texto;
  por eso se reporta el contexto y se elige por F1 con un presupuesto de contexto acotado.
- Con `k` fijo, el tamano del chunk condiciona tambien la precision (un chunk grande mezcla mas
  eventos) y el F1 favorece tamanos intermedios por construccion; la eleccion es una
  recomendacion razonada, no un optimo.
- Los commits recuperados se identifican por el sha corto de cada linea. Si una linea larga se
  parte entre chunks, el fragmento sin sha no cuenta: la cobertura de los chunks pequenos
  puede estar subestimada. Un mensaje que contenga el texto `commit xxxxxxx:` produciria un
  falso positivo (no observado).
- Los comentarios de PR e issues cuentan en las senales de arquetipos pero no se documentan
  (el esquema no guarda su texto): el agente no podra citarlos como evidencia (issues 9 y 13).
- Los chunks que no son el primero no repiten la cabecera con el desarrollador; la recuperacion
  (issue 9) debe propagar los metadatos (`desarrollador`, `repositorio`, `id`) junto al texto.
- Las consultas estan en espanol y los commits en ingles; el modelo es multilingue, pero no se
  midio el efecto del idioma.
- Pendiente de reevaluar en el issue 9 con la base vectorial real y en el issue 13 con la
  evaluacion de extremo a extremo.

## Pruebas automaticas

`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verificar.ps1` (lint con ruff y
pytest). Estado tras el issue 8: lint sin errores, 224 pruebas pasadas y 3 omitidas.
`tests/test_perfiles.py` cubre documentos de perfil (atribucion, metadatos, revisiones de PR
propios, issues) y segmentacion (metadatos, tamano maximo, configuracion invalida) con datos
sinteticos.

## Indexacion vectorial (issue 9)

Paquete `src/devmetrics/indexacion/` (`IndiceVectorial`, Chroma). Persiste en `data/chroma`
(no versionado); el indice se reconstruye volviendo a ejecutar `indexar` con los chunks de
`devmetrics.perfiles`, sin duplicados. Los embeddings los calcula `ModeloEmbeddings`, no Chroma.

- Metadatos por chunk: `desarrollador` (minusculas), `repositorio`, `tipo_fuente`, fechas
  (`fecha_desde`/`fecha_hasta` y su copia numerica AAAAMMDD, porque Chroma solo compara
  numeros), `chunk`, `n_chunks`, `id`, `huella` (hash de texto y metadatos).
- `indexar` sincroniza los grupos (desarrollador, repositorio, tipo de fuente) que recibe: no
  recalcula embeddings de chunks sin cambios, actualiza los modificados (texto o metadatos) y
  borra los sobrantes al final, para no perder datos si falla el embedder. Un grupo que
  desaparece por completo de la entrada no se purga solo: usar `eliminar`.
- `consultar` aplica filtros por desarrollador, repositorio, tipo de fuente y rango de fechas
  (solapamiento con la actividad del documento; sin fechas, el documento queda excluido al
  filtrar por fecha). Metrica coseno.
- Limites: las referencias llegan hasta el grupo y el rango de fechas; los metadatos no apuntan
  a eventos concretos (SHA, numero de PR). Pruebas con embeddings de bolsa de palabras
  deterministas; la consulta semantica real se comprobo solo con 3 documentos de ejemplo
  (`DEVMETRICS_INTEGRACION=1 pytest tests/test_indexacion_integracion.py`, 1 prueba pasada).
  No se ha indexado aun la muestra piloto.
- `tests/test_indexacion.py` (27 pruebas): filtros simples y combinados, fechas, orden por
  similitud, idempotencia (sin llamadas al embedder en la segunda pasada), actualizacion por
  texto y por metadatos, borrado de obsoletos, fallo del embedder, aislamiento de indices en
  memoria, purga y persistencia en disco.

## Fuente interna (issue 10)

Base de conocimiento ficticia en `conocimiento/*.md` (organizacion ficticia Andes Soluciones
Digitales): 3 requerimientos (estabilizacion de microservicios, portal de documentacion,
migracion a la nube), 3 definiciones de arquetipo (Druid, Cleric, Bard) y 1 documento de
criterios de asignacion. Cada archivo lleva una cabecera `clave: valor` (categoria, documento,
titulo, arquetipos). Paquete `src/devmetrics/conocimiento/`; indexacion con
`python scripts/indexar_conocimiento.py` en la coleccion `conocimiento` de `data/chroma`.

- Decision de esquema: se generalizo `IndiceVectorial` con `claves_grupo` (los documentos
  internos se agrupan por `tipo_fuente` y `documento`, no por desarrollador) y el filtro
  generico `filtros` en `consultar` (p. ej. `categoria`). Los perfiles no cambian.
- Los chunks anteponen el titulo del documento, porque los posteriores al primero no lo repiten.
- `recuperar_para_proyecto(consulta, conocimiento, perfiles)`: (1) requerimiento mas cercano,
  (2) definiciones de los arquetipos que declara, (3) perfiles cercanos al texto de esas
  definiciones y a la consulta. Las definiciones aportan el vocabulario de actividad (Dockerfile,
  pruebas, README) que el requerimiento no usa.
- Pruebas: `tests/test_conocimiento.py` (cargador, cabeceras invalidas, ids repetidos, chunking,
  idempotencia, filtro por categoria, validez de la base real y recuperacion con embeddings de
  bolsa de palabras) y `tests/test_conocimiento_integracion.py` con embeddings reales
  (`DEVMETRICS_INTEGRACION=1`): las 3 consultas "perfil adecuado para ..." recuperan el
  requerimiento esperado y, con k=1, el perfil esperado.
- Resultado de la integracion: ejecutada con `DEVMETRICS_INTEGRACION=1` (2 pruebas del issue
  pasadas junto a las unitarias). Los perfiles de las pruebas con bolsa de palabras solo se
  comprueban por cantidad y tipo, no por orden.
- `distancia_maxima` descarta requerimientos lejanos (consulta ajena -> contexto vacio); con embeddings reales una consulta ajena queda mas lejos que las 3 propias en la prueba de integracion, pero el
  valor concreto del umbral no esta calibrado. `cargar_documentos` valida que cada
  arquetipo declarado tenga su documento `arquetipo-<nombre>`.
- Los perfiles recuperados son chunks: varios pueden ser del mismo desarrollador (agrupar es
  tarea del agente). Un `.md` borrado de `conocimiento/` queda en el indice hasta usar
  `eliminar(tipo_fuente="conocimiento_interno", ...)`; el script no purga grupos ausentes.
- Limites: la integracion usa 3 perfiles sinteticos y 3 consultas (verifica el mecanismo, no
  la calidad con la muestra piloto, que aun no esta indexada); el vinculo requerimiento ->
  arquetipo es declarado a mano en la cabecera, no inferido; el paso 3 no usa la mezcla de
  arquetipos calculada por `devmetrics.arquetipos` (queda para el agente, issues 11 y 12).

## Recuperador combinado y herramienta en vivo (issue 11, IE3)

Paquete `src/devmetrics/recuperacion/`.

- `RecuperadorCombinado(conocimiento, perfiles, en_vivo=None).recuperar(consulta, ...)` consulta
  la fuente interna (filtro `categoria`) y la externa (filtros `desarrollador`, `repositorio`,
  `tipo_fuente`, `desde`, `hasta`), mezcla por distancia y devuelve una `Recuperacion`. `k` limita
  el total; `k_interna` y `k_externa`, cada fuente (por defecto 2 y 4). `distancia_maxima` descarta
  fragmentos lejanos. Las distancias son comparables porque ambas colecciones usan el mismo modelo.
- Citas: cada `Fragmento` lleva `cita` (documento y fragmento para la fuente interna; repositorio,
  tipo, login, rango de fechas y fragmento para GitHub, con la marca "[consulta en vivo]" si
  viene de la API). `Recuperacion.fuentes` lista las citas unicas y `formatear()` las imprime tras
  cada fragmento, de modo que la respuesta del agente puede listar sus fuentes.
- Fuente caida: cada fuente se consulta aislada; si una lanza una excepcion, la otra responde y el
  fallo queda en `avisos`. Con todas caidas, `sin_resultados` y el texto "SIN RESULTADOS (motivo)".
  Una fecha invalida es error del llamador (`ValueError`) y no se trata como fuente caida.
- Herramienta en vivo: `consultar_en_vivo` descarga con la ingesta (cache local si existe), documenta
  y segmenta como los perfiles indexados y consulta un indice efimero en memoria; un repositorio
  que falla no bloquea a los demas. `crear_herramienta_github` la expone como `StructuredTool`
  (`consultar_github`) y nunca propaga excepciones: devuelve "SIN RESULTADOS (...)". El recuperador
  consulta GitHub solo si se pide un desarrollador sin ningun fragmento indexado (con o sin
  filtros) y se entrego `en_vivo` (adaptador `crear_en_vivo(repositorios, cliente, embeddings)`);
  los filtros (repositorio, tipo, fechas) se propagan a la consulta en vivo. Un fallo de esa fuente
  queda como aviso. Los avisos acotan el mensaje de la excepcion a 120 caracteres.
  Restriccion: indices y adaptador en vivo deben usar el mismo modelo de embeddings (no se valida).
- Pruebas: `tests/test_recuperacion.py` (20): combinacion y citas, filtros, k, consulta sin
  resultados (umbral, filtros, indices vacios), fuente externa caida, todas caidas, fallback en vivo
  solo si no esta indexado, GitHub caido, repositorio caido entre varios, sin actividad, herramienta.
  Usan embeddings de bolsa de palabras y el cliente falso de GitHub.
- Limites: no probado con la API real ni con embeddings reales; un desarrollador indexado solo en
  otro repositorio no activa la consulta en vivo (el criterio es "sin fragmentos para el login");
  la ingesta en vivo descarga hasta 100 commits, 50 PR y 50 issues por repositorio y una solicitud
  por commit, lo que sin token agota el limite de tasa; `distancia_maxima` sigue sin calibrar.

## Issue 12: cadena RAG y conversacion

- `devmetrics.agente.Conversacion` recupera con `RecuperadorCombinado`, arma el prompt `sistema`
  (v1.1.0, nueva variable `{contexto}` entre `<contexto>`) con contexto, historial y consulta, y
  responde con las fuentes citadas. `MemoriaVentana(n)` guarda los ultimos `n` mensajes (usuario y
  asistente cuentan aparte); no se usa `langchain-classic` ni langgraph.
- Evidencia insuficiente: sin fragmentos no se llama al LLM y la respuesta es determinista
  ("Evidencia insuficiente: ..." con los avisos de fuentes caidas). Si el LLM la declara, la
  respuesta no lista fuentes. Consulta vacia: se pide precisar sin recuperar.
- Ambiguedad: la resuelve el prompt (regla "pide que se precise"); la prueba solo comprueba que
  la regla viaja en el prompt y que la respuesta del LLM se devuelve intacta.
- Seguimiento: una consulta de hasta 8 palabras se busca junto a la ultima pregunta que tuvo
  evidencia (no hereda las que quedaron sin ella);
  las mas largas se buscan solas. Heuristica no calibrada.
- Un fallo del LLM propaga y el turno no se guarda en la memoria.
- Pruebas: `tests/test_agente.py` (19) con recuperador y LLM falsos: prompt aumentado, sin
  contexto, evidencia insuficiente declarada, ambigua, vacia, seguimiento, ventana, filtros,
  fallo del LLM, inyeccion por delimitador y reinicio.
- Limites: no probado con LLM ni embeddings reales (el comportamiento ante ambiguedad y la
  fidelidad de las citas se miden en el issue 16); la deteccion de "evidencia insuficiente" del LLM
  busca la frase en las dos primeras lineas (tolera markdown); los avisos de fuentes caidas se
  muestran al usuario en la respuesta determinista; sin herramienta en vivo integrada en la cadena (solo via el recuperador).
