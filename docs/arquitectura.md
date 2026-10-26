# Arquitectura y plan por fases

## 1. Problema

Los correos que llegan a la entidad son PQRSF (peticiones, quejas, reclamos,
sugerencias y felicitaciones), pero **el remitente no usa esas palabras**. Hoy
alguien los lee, decide qué son, los radica en el Sistema de Gestión Documental
(SGD) y los asigna a un área.

Se quiere automatizar ese recorrido y, cuando algo no se pueda radicar, recibir
un Excel diario con el motivo.

## 2. Decisiones tomadas

| Decisión | Elección | Por qué |
|---|---|---|
| Origen del correo | Gmail API (Google Workspace) | API oficial, etiquetas nativas para marcar procesados |
| Destino | SGD aún no definido | Se define un contrato propio y se trabaja contra un mock |
| Clasificación | Reglas + IA con umbral | Las reglas son auditables; la IA cubre redacciones no estándar |
| Stack | Python 3.14 | Correo, Excel y clasificación en un solo lenguaje |
| Persistencia | SQLite | Sin infraestructura adicional; suficiente para este volumen |

## 3. Las dos garantías que sostienen el sistema

### Garantía 1 — No duplicar radicados

Un radicado duplicado en un SGD es un documento oficial con número, que hay que
anular a mano. Por eso hay **dos barreras independientes**:

```
   ┌─────────────────────────────┐
   │ 1. Estado local (SQLite)    │  ¿Message-ID ya está en estado RADICADO?
   │    state.puede_radicar()    │  -> si sí, no se llama al SGD
   └──────────────┬──────────────┘
                  │ pasa
   ┌──────────────▼──────────────┐
   │ 2. Idempotency-Key en el SGD│  cabecera = Message-ID
   │    (contrato, punto 6)      │  -> el SGD devuelve el existente
   └─────────────────────────────┘
```

Verificado en `tests/test_idempotencia.py`: procesar dos veces el mismo correo
crea **un** radicado, incluso si se borra el estado local.

### Garantía 2 — No radicar correos dudosos

Tres salidas, no dos:

| Ruta | Condición | Consecuencia |
|---|---|---|
| `RADICADO` | confianza ≥ umbral (0.75) y tipo identificado | Se radica y se asigna |
| `REVISION` | confianza < umbral, o tipo desconocido | **No** se radica; aparece en el Excel |
| `FALLIDO` | error técnico (SGD caído, timeout, datos inválidos) | Se reintenta; aparece en el Excel |

Radicar un correo mal clasificado es peor que no radicarlo: obliga a anular un
documento oficial. Por eso el sistema prefiere dejar trabajo manual antes que
generar basura.

## 4. Flujo

```
                 ┌──────────────┐
   Gmail API ───▶│  1. Ingesta  │  lista, descarga cuerpo + adjuntos
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │  2. Registro │  INSERT si no existe (Message-ID)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │3. Clasificar │  reglas -> ¿confianza? -> IA
                 └──────┬───────┘
              ┌─────────┴─────────┐
        confianza baja        confianza alta
              ▼                   ▼
      ┌──────────────┐    ┌──────────────┐
      │  REVISION    │    │ 4. Radicar   │  POST /radicados
      │ (humano)     │    │    en SGD    │  + Idempotency-Key
      └──────┬───────┘    └──────┬───────┘
             │            ┌──────┴──────┐
             │            ▼             ▼
             │      ┌──────────┐  ┌──────────┐
             │      │ RADICADO │  │ FALLIDO  │
             │      └────┬─────┘  └────┬─────┘
             │           ▼             │
             │      ┌──────────┐       │
             │      │5. Asignar│       │
             │      └──────────┘       │
             └───────────┬─────────────┘
                         ▼
                 ┌──────────────┐
                 │ 6. Excel día │  no radicados + motivo
                 └──────────────┘
```

## 5. Fases

### Fase 0 — Contratos y credenciales (bloqueante)

- [x] Contrato del SGD en `contracts/radicacion.openapi.yaml`
- [x] Mock del SGD en `mock/sgd_mock.py`
- [x] Modelo de estado con idempotencia
- [ ] **Elegir el SGD** y verificar si cumple el contrato
- [ ] Proyecto en Google Cloud + credenciales OAuth de Gmail
- [ ] Catálogo real de áreas y usuarios

**Criterio de aceptación:** el SGD elegido puede crear un radicado de forma
idempotente y asignarlo a un área.

### Fase 1 — Ingesta de Gmail (sin radicar)

- [ ] Autenticación OAuth con scopes `gmail.readonly` + `gmail.modify`
- [ ] Listar correos con `GMAIL_QUERY`, descargar cuerpo y adjuntos
- [ ] Normalizar HTML a texto plano
- [ ] Aplicar etiqueta de prueba (sin radicar nada)

**Criterio de aceptación:** correr el proceso sobre el buzón real produce un
listado de correos normalizados y **ningún efecto** en el SGD.

### Fase 2 — Clasificación

- [x] Motor de reglas con umbral
- [ ] Afinar `config/areas.yaml` con correos reales (lo hace el negocio)
- [ ] Clasificador IA como respaldo
- [ ] Medir aciertos sobre una muestra etiquetada a mano

**Criterio de aceptación:** ≥ 80% de acierto en tipo y área sobre 50 correos
reales revisados por una persona.

### Fase 3 — Radicación real

- [ ] Adaptar `radicar.py` al SGD elegido
- [ ] Reintentos con espera progresiva
- [ ] Prueba controlada con 1 correo real

**Criterio de aceptación:** cada correo radicado tiene número y es consultable
en el SGD.

### Fase 4 — Asignación

- [ ] Catálogo real de áreas y usuarios
- [ ] Regla de asignación (área, luego usuario)
- [ ] Verificar en el SGD que el radicado queda asignado

### Fase 5 — Reporte diario

- [x] Generación del Excel (`report.py`)
- [ ] Programación diaria (Programador de tareas de Windows o cron)
- [ ] Envío por correo a los destinatarios de `REPORT_RECIPIENTS`

**Criterio de aceptación:** el Excel llega todos los días a la hora acordada y
sus filas coinciden con el estado real.

## 6. Riesgos conocidos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El SGD no implementa idempotencia | Radicados duplicados | Exigirlo en la contratación; si no, mantener la barrera local y no reintentar a ciegas |
| El SGD no tiene API | Bloquea las fases 3-4 | Evaluar RPA o carga masiva; cambia el alcance |
| Credenciales OAuth de Gmail | La app puede requerir verificación de Google si es externa | Usar tipo "Interno" en el consentimiento si el dominio es propio |
| El buzón es compartido | Varias personas leen el mismo correo | La etiqueta marca el procesado; coordinar con el equipo |
| Datos personales en un repo público | Sanción legal | `.gitignore` bloquea `var/`, `credentials/`, `.env` |

## 7. Pendiente de decidir

1. **Qué SGD** y si expone API.
2. **Dominio del buzón** y si hay un administrador de Google Workspace que
   pueda autorizar la app.
3. **Horario y destinatarios** del reporte diario.
4. **Catálogo de áreas** real y quién es el responsable de cada una.
