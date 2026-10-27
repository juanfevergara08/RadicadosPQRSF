# RadicadosPQRSF

Radicación automática de **PQRSF** (peticiones, quejas, reclamos, sugerencias y
felicitaciones) a partir de los correos que llegan a la entidad.

El sistema lee el buzón, clasifica cada correo, lo radica en el Sistema de
Gestión Documental (SGD), lo asigna al área correspondiente y envía un Excel
diario con lo que no se pudo radicar y por qué.

> **Repositorio público.** Aquí solo va **código**. Nunca datos reales de
> radicantes, credenciales ni archivos `.env`.

📐 Diseño, fases y riesgos: [`docs/arquitectura.md`](docs/arquitectura.md)

---

## Estado actual

| Fase | Estado |
|---|---|
| 0. Contratos y mock del SGD | ✅ |
| 1. Ingesta de Gmail | ✅ |
| 2. Clasificación por reglas | ✅ (IA pendiente) |
| 3. Radicación real (RPA) | 🚧 en reconocimiento |
| 4. Asignación | ⛔ depende de la fase 3 |
| 5. Reporte diario | ✅ generación (envío pendiente) |

**Destino:** DocxFlow (`docxflow.camarapereira.org.co`), radicados `CCPE<AA>-<NNNN>`.
**Buzones:** pruebas `jvergara@camarapereira.org.co`, producción
`unidadcorrespondencia@camarapereira.org.co`.

> ⚠️ `SGD_MODO_PRUEBA=true` mantiene el sistema sin escribir en DocxFlow. No lo
> pongas en `false` hasta validar la fase 3.

---

## Cómo correr la demo

No necesita Gmail, ni SGD, ni conexión a internet. Levanta un SGD falso en
memoria y hace pasar correos de ejemplo por todo el recorrido.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

python run_demo.py
```

Salida esperada: 2 radicados, 2 a revisión, 1 fallido, un reintento que **no**
duplica el radicado, y el Excel en `var/reportes/`.

## Leer correos reales (fase 1)

```bash
python scripts/verificar_gmail.py          # comprueba la configuración OAuth
python scripts/ingestar.py --limite 10     # lee y clasifica, sin radicar
```

`--guardar` escribe el JSON en `var/correos/` para calibrar el clasificador.
`--etiquetar` pone la etiqueta `PQRSF-Leido` en Gmail.

## Reconocimiento de DocxFlow (fase 3)

```bash
pip install playwright
playwright install chromium
python scripts/reconocer_docxflow.py --confirmar
```

Inicia sesión, guarda captura + HTML + lista de campos en `var/rpa/`.
**No envía ningún formulario de radicación.**

## Cómo correr las pruebas

```bash
python -m unittest discover -s tests -t .
```

Cubren la garantía más importante del sistema: **un correo nunca se radica dos
veces**.

---

## Estructura

```
contracts/
  radicacion.openapi.yaml   Contrato que se espera del SGD (aún sin proveedor)
config/
  areas.yaml                Tipos PQRSF y áreas con sus palabras clave
mock/
  sgd_mock.py               SGD falso, idempotente, para desarrollo
src/radicados/
  models.py                 Correo, Clasificación, Resultado (sin dependencias)
  config.py                 Variables de entorno y catálogo
  state.py                  SQLite: la barrera contra radicados duplicados
  classify.py               Reglas + umbral + gancho para IA
  radicar.py                Cliente del SGD según el contrato
  report.py                 Excel de no radicados
  proceso.py                Orquesta el recorrido completo
tests/                      Pruebas de clasificación, estado e idempotencia
run_demo.py                 Demo end-to-end
```

---

## Configuración local

```bash
cp .env.example .env
```

Completa en `.env` las credenciales de Google y la URL del SGD. Ese archivo
nunca se sube.

---

## Cómo colaborar

### 1. Clona y crea tu rama

Nunca trabajes directamente sobre `main`.

```bash
git clone https://github.com/juanfevergara08/RadicadosPQRSF.git
cd RadicadosPQRSF
git switch -c feature/nombre-de-tu-tarea
```

### 2. Haz cambios y commitea

```bash
git status                 # revisa qué cambió
git add archivo1 archivo2  # evita "git add ." a ciegas
git commit -m "feat(radicados): crear formulario de radicación"
```

### 3. Sube tu rama

```bash
git push -u origin feature/nombre-de-tu-tarea
```

### 4. Abre un Pull Request

En GitHub, abre un PR de tu rama hacia `main`. Otro compañero lo revisa y lo
aprueba. **Nadie hace push directo a `main`.**

---

## Estrategia de ramas

| Rama | Uso |
|---|---|
| `main` | Versión estable, siempre funciona |
| `feature/...` | Una funcionalidad nueva |
| `fix/...` | Corrección de un error |

## Convención de commits

```
<tipo>(<alcance>): <descripción en imperativo>
```

Tipos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.

---

## Reglas del repositorio

- ❌ No subir datos personales de radicantes (Ley 1581 de 2012).
- ❌ No subir `.env`, llaves, certificados ni `credentials/`.
- ❌ No subir `var/` (base de estado y reportes contienen datos reales).
- ✅ Usar `.env.example` para documentar qué variables se necesitan.
- ✅ Toda funcionalidad nueva llega con su prueba.
