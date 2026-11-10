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
