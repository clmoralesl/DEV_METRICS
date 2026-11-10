---
categoria: requerimiento
documento: req-migracion-nube
titulo: Migracion de la plataforma de datos a la nube
arquetipos: druid
---
# Requerimiento REQ-2026-018: migracion de la plataforma de datos a la nube

Cliente interno: Gerencia de Tecnologia de Andes Soluciones Digitales (organizacion ficticia).
Estado: en planificacion. Duracion estimada: 16 semanas. Equipo solicitado: 2 personas.

## Contexto
La plataforma de datos corre en servidores propios con despliegues manuales. Se migrara a un
proveedor de nube con infraestructura como codigo.

## Alcance
- Definir la infraestructura con Terraform y archivos YAML de despliegue.
- Automatizar pipelines de integracion y entrega continua con GitHub Actions y contenedores Docker.
- Migrar bases de datos con scripts SQL y migraciones versionadas.

## Perfil buscado
Perfil de infraestructura (Druid): historial de Terraform, Docker, Kubernetes, pipelines,
migraciones de base de datos y configuracion de despliegue. La documentacion operativa es un
complemento.

## Criterios de aceptacion
- Toda la infraestructura descrita como codigo y reproducible desde cero.
- Migracion de datos sin perdida verificada con scripts de comparacion.
