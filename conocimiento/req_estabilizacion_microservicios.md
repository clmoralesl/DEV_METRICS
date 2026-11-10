---
categoria: requerimiento
documento: req-estabilizacion-microservicios
titulo: Estabilizacion de microservicios de facturacion
arquetipos: cleric,druid
---
# Requerimiento REQ-2026-014: estabilizacion de microservicios de facturacion

Cliente interno: Direccion de Finanzas de Andes Soluciones Digitales (organizacion ficticia).
Estado: abierto. Duracion estimada: 10 semanas. Equipo solicitado: 2 personas.

## Contexto
Los microservicios de facturacion y cobranza presentan caidas intermitentes en horario de cierre
mensual. Hay errores recurrentes de tiempo de espera entre servicios, colas que se saturan y
despliegues que fallan por configuracion inconsistente entre ambientes.

## Alcance
- Corregir los errores recurrentes y las regresiones que originan las caidas (bug fixes con prueba
  de regresion).
- Revisar con rigor los cambios de otros integrantes: todo pull request al repositorio de
  facturacion requiere una revision antes de fusionar.
- Estabilizar la infraestructura: pipelines de despliegue, archivos de Docker y Kubernetes,
  migraciones de base de datos y monitoreo.
- Ampliar la cobertura de pruebas de los servicios criticos.

## Perfil buscado
Predomina el perfil de correccion y revision (Cleric): historial de correcciones de errores,
revisiones de pull requests ajenos y pruebas. Se complementa con trabajo de infraestructura
y despliegue (Druid) para los pipelines y la configuracion. No se requiere trabajo de
interfaz ni de documentacion extensa.

## Criterios de aceptacion
- Cero caidas del servicio de facturacion durante dos cierres mensuales consecutivos.
- Cobertura de pruebas de los servicios criticos sobre el 70 %.
- Pipeline de despliegue reproducible en los tres ambientes.
