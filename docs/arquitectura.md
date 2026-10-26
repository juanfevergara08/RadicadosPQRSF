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
| Origen del correo | Gmail API (Google Workspace, dominio `camarapereira.org.co`) | API oficial, etiquetas nativas para marcar procesados |
| Buzón de pruebas | `jvergara@camarapereira.org.co` | Permite leer correos reales sin tocar la unidad |
| Buzón de producción | `unidadcorrespondencia@camarapereira.org.co` | Donde llegan las PQRSF de verdad |
| Destino | **DocxFlow** (`docxflow.camarapereira.org.co`) | Es el SGD de la Cámara |
| Numeración | `CCPE<AA>-<NNNN>`, reinicia cada año | La genera DocxFlow, no nosotros |
| Clasificación | Reglas + IA con umbral | Las reglas son auditables; la IA cubre redacciones no estándar |
| Stack | Python 3.14 | Correo, Excel y clasificación en un solo lenguaje |
| Persistencia | SQLite | Sin infraestructura adicional; suficiente para este volumen |

## 2.1 Estado real de DocxFlow (verificado 2026-10-26)

Probé el sistema sin credenciales buscando documentación pública:

| Ruta | Respuesta | Lectura |
|---|---|---|
| `/api` | `{"error":{"code":404,...}}` | Existe un prefijo de API |
| `/api/docs`, `/api/docs.json` | 404 | Sin Swagger/OpenAPI |
| `/swagger`, `/openapi.json` | 404 con página de error de **Symfony** | Aplicación PHP/Symfony |
| `/login` | `PHPSESSID` + frame-buster | Autenticación por sesión y cookie |

**Conclusión:** DocxFlow es una aplicación Symfony con un `/api` interno que
consume su propio frontend, pero **no publica documentación ni endpoints**. No
se puede integrar por API sin intervención del proveedor.

### Qué hay que pedirle a DocxFlow (en orden de preferencia)

1. **Documentación del API** y credenciales (token o usuario técnico).
2. Un **endpoint de radicación** para integraciones.
3. Si no existe: confirmarlo por escrito y evaluar automatización de navegador
   (RPA) como plan B.

### Los tres datos que faltan y bloquean la fase 3

| Dato | Para qué |
|---|---|
| Catálogo de **tipos de trámite** | DocxFlow radica por trámite, no por tipo PQRSF. Son taxonomías distintas. |
| Catálogo de **usuarios por área** | El radicado se distribuye a un usuario concreto (el que responde). |
| Catálogo de **clasificación de anexos** | Cada adjunto debe clasificarse al radicar. |

Mientras no existan, `config/areas.yaml` tiene valores provisionales marcados
como `PENDIENTE`. El sistema los usa contra el mock, pero **no son válidos
para producción**.

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

### Fase 0 — Contratos y credenciales

- [x] Contrato del SGD en `contracts/radicacion.openapi.yaml`
- [x] Mock del SGD en `mock/sgd_mock.py` con numeración real `CCPE<AA>-<NNNN>`
- [x] Modelo de estado con idempotencia
- [x] SGD identificado: DocxFlow
- [ ] **Documentación del API de DocxFlow** ← bloqueante
- [ ] Proyecto en Google Cloud + credenciales OAuth de Gmail
- [ ] Catálogo real de trámites, usuarios y clasificación de anexos

**Criterio de aceptación:** DocxFlow entrega documentación de API y credenciales,
y confirma que soporta `Idempotency-Key`.

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

> **Bloqueada** hasta tener la documentación del API de DocxFlow.

- [ ] Conseguir documentación y credenciales de DocxFlow
- [ ] Adaptar `radicar.py` al API real (hoy implementa nuestro contrato)
- [ ] Reintentos con espera progresiva
- [ ] Prueba controlada con 1 correo real
- [ ] Poner `SGD_MODO_PRUEBA=false` **solo** después de esa prueba

**Criterio de aceptación:** cada correo radicado tiene número `CCPE<AA>-<NNNN>`
y es consultable en DocxFlow.

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
| **DocxFlow no documenta su API** | Bloquea las fases 3-4 | Pedirla al proveedor; si no existe, evaluar RPA con el área de sistemas |
| DocxFlow no implementa idempotencia | Radicados duplicados | Exigirlo; si no, mantener la barrera local y no reintentar a ciegas |
| Catálogos de trámite/usuario desconocidos | No se puede mapear ni distribuir | Obtenerlos de DocxFlow antes de la fase 3 |
| Credenciales OAuth de Gmail | Puede requerir verificación de Google | Usar consentimiento tipo "Interno" en el dominio `camarapereira.org.co` |
| Probar contra el DocxFlow real | Crea radicados oficiales de prueba | `SGD_MODO_PRUEBA=true` fuerza el mock y lo impide |
| El buzón es compartido | Varias personas leen el mismo correo | La etiqueta marca el procesado; coordinar con la unidad |
| Datos personales en un repo público | Sanción legal | `.gitignore` bloquea `var/`, `credentials/`, `.env` |

## 7. Pendiente de decidir

1. **Documentación del API de DocxFlow.** Es lo único que bloquea la fase 3.
2. **Catálogo de tipos de trámite** de DocxFlow.
3. **Usuarios por área** (los destinatarios reales).
4. **Clasificación de anexos** que exige DocxFlow.
5. **Horario y destinatarios** del reporte diario.
6. **Quién administra Google Workspace** para autorizar la app.
