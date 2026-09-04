# SC20260826001

Sistema de verificación de identidad para postulantes de la Policía Nacional del Ecuador (SECURE_CODE).

## Cómo iniciar

1. Lee el plan: [`docs/PLAN-PASO-A-PASO.md`](docs/PLAN-PASO-A-PASO.md)
2. Completa el día 1: [`docs/CHECKLIST-DIA-1.md`](docs/CHECKLIST-DIA-1.md)
3. Trabaja siempre desde `DEVOPS` (nunca directo en `PRODU`)

## Ramas

| Rama | Uso |
| --- | --- |
| `DEVOPS` | Integración diaria de desarrollo |
| `TEST` | QA y demostración |
| `PRODU` | Producción |

Flujo: `feature/...` → `DEVOPS` → `TEST` → `PRODU`

## Stack

- Frontend: Angular
- Backend: Python (Django + Django REST Framework)
- Reconocimiento facial: InsightFace, llamado en proceso desde Django (sin microservicio aparte)
- Base de datos: PostgreSQL
- Hosting: DigitalOcean o Hetzner (**no AWS**)
