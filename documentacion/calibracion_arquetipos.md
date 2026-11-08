# Modelo de arquetipos y calibración de umbrales (issue 4)

Indicador IE1. Implementación en `src/devmetrics/arquetipos/`; configuración por defecto en `src/devmetrics/arquetipos/configuracion_defecto.json`. Los desarrolladores de la muestra se identifican con alias (D1 a D5 Druid, B1 a B5 Bard, C1 a C5 Cleric, M1 a M4 mixtos); la correspondencia con los logins queda fuera del repositorio (RNF6).

## 1. Señales y mapeo a las clases

Las definiciones del caso son: Druid (bases de datos, arquitectura, infraestructura), Cleric (soporte, revisión, resolución de bugs) y Bard (frontend, documentación, trabajo en equipo). Los pesos se derivaron de esas definiciones y no se modificaron al contrastarlos con la muestra.

| Señal | Cómo se obtiene | Clase que alimenta |
| ----- | --------------- | ------------------ |
| Archivos de infraestructura y datos | Diccionario de rutas configurable (`.tf`, `.sql`, YAML, Dockerfile, `k8s/`, `migrations/`, `.github/`) | Druid |
| Archivos de documentación y frontend | Diccionario de rutas (`.md`, `docs/`, `.tsx`, `.css`) | Bard |
| Comentarios en PR e issues ajenos | Conteo, saturado (trabajo en equipo) | Bard |
| Commits de corrección | Tipo de cambio por contenido y archivos, no por prefijo | Cleric |
| Revisiones de PR ajenos | Conteo, saturado | Cleric |
| Issues atendidos | Conteo, saturado (soporte) | Cleric |
| Archivos de pruebas | Diccionario de rutas | Cleric (peso bajo) |
| Volumen | commits + revisiones + comentarios + issues | Confianza |
| Diversidad | repositorios distintos (alta exige más de uno; con repositorio desconocido no hay confianza alta). Las categorías con al menos 10 % de los archivos se calculan como dato informativo y no entran en el puntaje ni en la confianza | Confianza |

Los archivos de código general no puntúan para ninguna clase. El tipo de cambio de un commit que toca solo documentación o solo infraestructura toma ese tipo antes de evaluar palabras de corrección, de modo que "fix typo" en la documentación no cuenta como corrección. El tipo puede venir inyectado (campo opcional del commit) para que el LLM lo reemplace en los issues 5 y 13.

Puntaje bruto por clase (pesos en la configuración): Druid = infraestructura; Bard = documentación + frontend + 0,25 por comentarios; Cleric = 0,4 por corrección + 0,4 por revisiones + 0,1 por pruebas + 0,1 por issues. Revisiones, comentarios e issues se saturan como n/(n+k) con k = 100, 50 y 20. Los puntajes finales son los brutos normalizados para que sumen 1. Sin ninguna señal, el reparto es uniforme (1/3 cada clase).

## 2. Reglas de estado

1. Volumen menor al mínimo: `datos_insuficientes`, sin clase dominante, confianza baja; se informa la tendencia y cuántos eventos faltan.
2. Evidencia total menor al mínimo, o margen entre la primera y la segunda clase menor al umbral: `mixto`.
3. En otro caso: `dominante`. Un margen exactamente igual al umbral cuenta como dominante.
4. Confianza: baja bajo 30 eventos, media desde 30, alta desde 100 con más de un repositorio.

## 3. Calibración

Datos: agregados de la muestra piloto (15 etiquetados más 4 perfiles mixtos fuera de la muestra), medidos sobre 20 a 30 commits recientes. Los agregados entran directamente como señales: la calibración valida el puntaje y los umbrales, no la extracción desde commits crudos. El fix% de la muestra se midió por palabras sin la prioridad de documentación o infraestructura, por lo que sobrestima la corrección en los Bard. Para dos Cleric no se midieron los archivos (se registran como código general) y para algunos perfiles no se midió el fix% (se registra 0).

Solo se calibraron los umbrales, no los pesos, porque las etiquetas de la muestra salen de reglas sobre señales parecidas y ajustar los pesos a ellas sería circular.

Márgenes obtenidos:

| Grupo | Margen entre primera y segunda clase |
| ----- | ------------------------------------ |
| Positivos con menor margen | C3 0,116; C2 0,163; B3 0,233; D5 0,330 |
| Mixtos esperados | M2 0,084; M1 0,137; M4 0,197; M3 sin competencia (sin datos de revisiones) |

| Margen mínimo | Dominantes correctos (de 15) | Mixtos sin clase (de 4) |
| ------------- | ---------------------------- | ----------------------- |
| 0,10 | 15 | 2 |
| 0,15 | 14 | 3 |
| 0,20 | 13 | 4 |
| 0,25 | 12 | 4 |

No existe un margen que clasifique a los 15 y marque a los 4 mixtos: el intervalo factible está vacío (el mayor margen de un mixto, 0,197, supera al de dos positivos). La tendencia (clase de mayor puntaje) coincide con la etiqueta en los 15 casos. Se eligió 0,20 porque protege contra la clase forzada (CA7), a costa de dos Cleric de reseña intensa y documentación alta (C2 y C3) que quedan como mixtos; 13 de 15 supera la referencia de 11 de 15 (CA1). El mixto M4 queda por solo 0,003 bajo el umbral, por lo que ese resultado es frágil. Con una mayor cantidad de datos el umbral debe revisarse.

Evidencia mínima: los positivos tienen evidencia de 0,48 o más y el mixto de código general (M3, con datos incompletos) 0,33. Se fijó 0,40. Es un umbral débil, sustentado en un solo caso.

Volumen mínimo: la muestra no permite calibrarlo, porque cada integrante se midió sobre una ventana de 20 a 30 commits. El mínimo de 10 eventos es una decisión de diseño: con menos de 10 eventos, cada evento pesa 10 % o más de la actividad observada, comparable al margen exigido (0,20), por lo que la clase sería inestable. No se verificó con datos ni con una prueba de sensibilidad. Los cortes de confianza (30 y 100) son igualmente decisiones de diseño sin base empírica.

## 4. Límites conocidos

- Muestra dirigida de 15 y etiquetas derivadas de señales parecidas: la exactitud es optimista y no una verdad independiente.
- Un desarrollador con mucho código general y poca señal de arquetipo se resuelve con el umbral de evidencia; con pocos datos de la muestra.
- La confianza depende solo del volumen y de la diversidad de repositorios, tal como pide el issue. Un desarrollador con muchos commits pero sin revisiones ni issues obtiene confianza alta o media aunque su actividad sea acotada en tipo; queda como decisión pendiente del equipo para el caso CA5 (registrada en ESTADO.md).
- El perfil no incluye las señales ni los puntajes brutos que lo originaron, ni el origen (heurística o inyectado) del tipo de cambio de cada commit; el issue 8 deberá guardarlos si se necesita esa trazabilidad.
- Las pruebas de referencia están en `tests/test_perfil.py`, `tests/test_senales.py` y `tests/test_calibracion.py`; los agregados con alias, en `tests/muestra_agregados.py`.
