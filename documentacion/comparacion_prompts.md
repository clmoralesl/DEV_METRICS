# Comparación de técnicas de prompting: zero-shot, few-shot y cadena de pensamiento

ISY0101, Evaluación Parcial 1 (indicador IE2). Issue 5, prompt `tipo_cambio` versión 1.0.0 (RF6).

## 1. Qué se comparó

Tres formas de construir el mismo prompt (`devmetrics.prompts.Prompt.mensajes`):

- **zero-shot**: rol, restricciones y formato en el mensaje de sistema; tarea y entrada en el mensaje del usuario, sin ejemplos.
- **few-shot**: igual que zero-shot más 5 ejemplos (turnos usuario/asistente) definidos en `prompts/tipo_cambio.toml`.
- **cot** (cadena de pensamiento): igual que zero-shot más la instrucción de razonar en una clave `razonamiento` antes de decidir.

Conjunto de casos: `tests/casos_prompts/tipo_cambio.json`, 20 commits sintéticos (sin logins ni datos reales, RNF6) con etiqueta esperada, cubriendo los seis tipos. Incluye prefijos engañosos (`fix` sobre documentación, `feat` sobre un Dockerfile, `refactor` que agrega una función) y casos sin información (`wip`, una fusión sin archivos). Los 5 ejemplos few-shot no aparecen en el conjunto (lo verifica una prueba), aunque el caso T01 comparte el patrón "fix sobre documentación" con el primer ejemplo a propósito, porque enseña la regla de precedencia.

Métricas por llamada: tokens de entrada y de salida (`prompt_eval_count` y `eval_count` de Ollama), si la respuesta se extrae y pasa el validador (`validar_salida`, formato válido), si el tipo coincide con la etiqueta (exactitud, sobre todas las llamadas; un formato inválido cuenta como error) y la latencia.

Reproducción (Ollama activo con los modelos descargados):

```
.venv/Scripts/python.exe scripts/comparar_prompts.py --modelo qwen3:0.6b --repeticiones 3 --salida documentacion/comparacion_prompts_qwen3-0.6b.json
.venv/Scripts/python.exe scripts/comparar_prompts.py --modelo qwen3:4b --pensar --max-tokens 3000 --repeticiones 1 --salida documentacion/comparacion_prompts_qwen3-4b.json
```

Los resultados crudos (respuestas completas) están en los dos JSON de esta carpeta.

## 2. Decisiones de diseño del experimento

- Sin el parámetro `format` de Ollama: forzar el esquema haría trivial la consistencia de formato. La respuesta se parsea con un extractor tolerante y los fallos se cuentan.
- Temperatura 0.3 y semillas 1 a 3 (una por repetición).
- Dos modelos, por una limitación de `qwen3:4b`: en Ollama 0.40.15 es un modelo de razonamiento y `think: false` no lo desactiva (el razonamiento aparece igual en la respuesta; un bloque `<think>` vacío tampoco lo evita). Su razonamiento nativo se suma al de la técnica CoT y confunde la comparación. Por eso:
  - **Principal: `qwen3:0.6b` con `think: false`**, 20 casos x 3 repeticiones = 60 llamadas por técnica. Aísla el efecto de la técnica.
  - **Secundaria: `qwen3:4b` con pensamiento nativo activo**, 20 casos x 1 repetición = 20 llamadas por técnica. Sus tokens de salida incluyen el razonamiento nativo.
- Gemini no se usó (responde 403, ver `ESTADO.md`). Los resultados valen solo para estos dos modelos locales.

## 3. Resultados

### 3.1 qwen3:0.6b, sin pensamiento nativo (60 llamadas por técnica)

| Técnica | Formato válido | Exactitud | Tokens entrada (media) | Tokens salida (media) | Tokens totales | Latencia (media) |
| ------- | -------------- | --------- | ---------------------- | --------------------- | -------------- | ---------------- |
| zero-shot | 95,0 % | 45,0 % | 436,9 | 58,5 | 495,4 | 3,14 s |
| few-shot | 95,0 % | 70,0 % | 1598,9 | 36,7 | 1635,6 | 3,31 s |
| cot | 95,0 % | 35,0 % | 508,9 | 84,4 | 593,3 | 3,84 s |

### 3.2 qwen3:4b, con pensamiento nativo (20 llamadas por técnica)

| Técnica | Formato válido | Exactitud | Tokens entrada (media) | Tokens salida (media, con razonamiento nativo) | Tokens totales | Latencia (media) |
| ------- | -------------- | --------- | ---------------------- | ---------------------------------------------- | -------------- | ---------------- |
| zero-shot | 100 % | 95,0 % | 430,9 | 927,9 | 1358,8 | 111,2 s |
| few-shot | 100 % | 95,0 % | 1592,9 | 531,8 | 2124,7 | 80,8 s |
| cot | 100 % | 95,0 % | 502,9 | 784,0 | 1286,9 | 90,9 s |

## 4. Análisis

**Formato.** Con `qwen3:0.6b` las tres técnicas fallan en las mismas 3 de 60 llamadas, todas del caso T15 (`wip`, sin información): el modelo responde `"tipo": "no"` o `"no otro"` en lugar de usar `otro`. Es un fallo del contenido del prompt, no de la técnica: la definición de `otro` no dice que cubre los mensajes sin información. Con `qwen3:4b` el formato fue válido en el 100 % de las llamadas. Las respuestas con cercas de código se extraen sin problema.

**Exactitud.** En el modelo pequeño, few-shot es claramente mejor (70 % frente a 45 % de zero-shot, +25 puntos) y CoT es peor que zero-shot (35 %). Con 5 ejemplos el modelo acierta los casos con prefijo engañoso de documentación y los de corrección, pero sigue fallando T02 (`feat` sobre un Dockerfile), T05, T06, T08, T15 y T18: la regla de precedencia por archivos, refactor y `otro` no se aprenden con 5 ejemplos en un modelo de 0,6 B. El razonamiento escrito por el modelo pequeño no ayuda: lo lleva con frecuencia a `funcionalidad` (la confusión más frecuente en zero-shot fue corrección a funcionalidad, 8 de 60). Las repeticiones casi no cambian la salida (17 de 20 casos idénticos en zero-shot, 20 de 20 en las otras dos), así que las 3 repeticiones aportan poco más que una; la muestra efectiva es de 20 casos.

En `qwen3:4b` las tres técnicas empatan en 19 de 20, y fallan el mismo caso, T08 (`refactor: soporte de paginación...`, etiqueta `funcionalidad`): el modelo se queda con el prefijo, pese a la restricción. Con un caso por técnica y una repetición, el empate no distingue las técnicas.

**Costo en tokens.** Few-shot multiplica la entrada por 3,7 (1599 frente a 437 tokens) alargando poco la latencia en el modelo pequeño (3,3 s frente a 3,1 s); la entrada se procesa de forma barata frente a la generación. CoT añade unos 26 tokens de salida y 72 de entrada y empeora el resultado. En el modelo de razonamiento, few-shot tiene más tokens totales (2125 frente a 1359 de zero-shot y 1287 de CoT) pero la menor latencia media (80,8 s), porque los ejemplos acortan el razonamiento nativo (532 tokens de salida frente a 928).

## 5. Conclusión y decisión

Técnica por defecto para `tipo_cambio`: **few-shot**. Es la mejor en el modelo pequeño, empata en el grande y es la más rápida en este (con un costo mayor en tokens de entrada). CoT no se usa por defecto: no mejora en ningún modelo y en el pequeño empeora. El prompt conserva la instrucción de razonamiento para el uso con otros modelos.

Para `clasificacion_arquetipo` y `recomendacion` no se hizo la comparación (el issue la pide sobre un mismo conjunto de casos, y este conjunto es de tipo de cambio). Su técnica de partida es zero-shot con la opción de CoT; se decide al evaluarlos con datos reales (issues 13 y 16).

## 6. Limitaciones

- 20 casos sintéticos elaborados a mano; no hay intervalos de confianza, y las diferencias de pocos puntos no son concluyentes. La mejora de few-shot en el modelo pequeño (+25 puntos, 15 de 60 llamadas) sí supera esa incertidumbre, pero se apoya en solo 20 casos distintos.
- `qwen3:4b` se corrió con una sola repetición y su pensamiento nativo no se pudo apagar: la comparación entre técnicas en ese modelo está contaminada por él.
- Las etiquetas las fijó una sola persona sin segunda revisión; varias son discutibles (T17 índice de base de datos como infraestructura, T20 con prefijo `feat` sobre documentación).
- Los resultados no se extienden a Gemini ni a otros modelos.
- Mejora pendiente (versión 1.1 de `tipo_cambio`): aclarar que `otro` incluye los mensajes sin información y reevaluar. No se aplicó para no invalidar las mediciones de esta versión.
