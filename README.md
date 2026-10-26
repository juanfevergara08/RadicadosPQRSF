# RadicadosPQRSF

Sistema de radicación y seguimiento de **Peticiones, Quejas, Reclamos, Sugerencias y Felicitaciones (PQRSF)**.

> **Repositorio público.** Aquí solo va **código**. Nunca datos reales de radicantes,
> documentos de identidad, evidencias, credenciales ni archivos `.env`.

---

## Requisitos

_(Completar según el stack del proyecto)_

```bash
# Ejemplo
git clone https://github.com/juanfevergara08/RadicadosPQRSF.git
cd RadicadosPQRSF
```

## Configuración local

1. Copia el archivo de ejemplo de variables de entorno:

   ```bash
   cp .env.example .env
   ```

2. Completa tus valores en `.env`. **Ese archivo nunca se sube** (ya está en `.gitignore`).

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

En GitHub, abre un PR de tu rama hacia `main`. Otro compañero lo revisa y lo aprueba.
**Nadie hace push directo a `main`.**

---

## Estrategia de ramas

| Rama | Uso |
|---|---|
| `main` | Versión estable, siempre funciona |
| `develop` | Integración de trabajo en curso |
| `feature/...` | Una funcionalidad nueva |
| `fix/...` | Corrección de un error |

## Convención de commits

```
<tipo>(<alcance>): <descripción en imperativo>
```

Tipos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.

Ejemplos:

```
feat(radicados): agregar campo de número de radicado
fix(login): corregir validación de correo
docs(readme): documentar instalación
```

---

## Reglas del repositorio

- ❌ No subir datos personales de radicantes (Ley 1581 de 2012 – protección de datos).
- ❌ No subir `.env`, llaves, certificados ni contraseñas.
- ❌ No subir bases de datos ni evidencias.
- ✅ Usar `.env.example` para documentar qué variables se necesitan.
- ✅ Un Pull Request por funcionalidad, con descripción clara.

---

## Equipo

| Nombre | Rol |
|---|---|
| _(pendiente)_ | _(pendiente)_ |
