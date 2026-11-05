# Ciclo de trabajo por issue

El plan completo (hitos, issues, dependencias y mapa con la rubrica) esta en `documentacion/plan_issues.md`. Este archivo describe solo como se trabaja cada issue. Plazos de la pauta: propuesta de caso en semana 3, presentacion en semana 6, entrega en semana 7.

## Ciclo

1. Leer `ESTADO.md` y el issue. Si hace falta explorar, usar `explorador` (Haiku); para documentacion externa, `investigador` (Haiku).
2. Rama desde `origin/main`: `<tipo>/<descripcion-en-espanol>-issue-<N>`.
3. Plan de 5 a 10 lineas. En issues de tamano L o con decision de diseno, consultar al advisor antes de fijarlo. El usuario aprueba.
4. Implementar con `implementador` (Sonnet). Casos limite como pruebas automatizadas, no como comprobaciones manuales.
5. Ejecutar `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verificar.ps1` y leer solo `.claude/verificacion.md`.
6. Si falla dos veces por la misma causa: parar y consultar al advisor, sin tercer intento.
7. `revisor` revisa el diff y el informe de verificacion contra los criterios de aceptacion del issue.
8. Cierre: anotar decision, alternativas, justificacion y evidencia en `notas_equipo/bitacora_decisiones.md`; actualizar `ESTADO.md` (maximo 25 lineas); resumen y `git diff --stat` para aprobacion de commit; plantilla de PR con `Closes #N`.
9. Preparar el entorno del siguiente issue (o de los dos siguientes si son independientes): `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/preparar-issue.ps1 -Issue <N>[,<M>]`. Cada issue se trabaja en una conversacion nueva.

## Que automatizar con scripts (cero tokens)

- Lint, pruebas y conteos: `scripts/verificar.ps1`.
- Casos de consulta del agente (pregunta, perfil esperado, fuentes esperadas) en `tests/casos_agente.json`, ejecutados por pytest.
- Metricas de recuperacion y generacion calculadas por un script y guardadas en `documentacion/pruebas.md` como evidencia.
