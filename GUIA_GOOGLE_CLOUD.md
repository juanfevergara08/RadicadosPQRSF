# Configurar Google Cloud para leer unidadcorrespondencia@camarapereira.org.co

Sigue estos pasos en **https://console.cloud.google.com**.

## 1. Crear o seleccionar el proyecto

1. En la barra superior, clic en el **selector de proyecto** (arriba a la izquierda).
2. Clic en **NUEVO PROYECTO**.
3. Nombre: `radicados-pqrsf`
4. Ubicación: selecciona la organización de tu empresa si aparece, o deja "Sin organización".
5. Clic en **Crear** y espera a que se cree.
6. Selecciona el proyecto nuevo en el selector de proyectos.

## 2. Habilitar la Gmail API

1. Menú ☰ → **APIs y servicios** → **Biblioteca**.
2. Busca **"Gmail API"**.
3. Clic en el resultado y luego en **HABILITAR**.

## 3. Configurar la pantalla de consentimiento (OAuth)

1. Menú ☰ → **APIs y servicios** → **Pantalla de consentimiento de OAuth**.
2. Elige el tipo de usuario:
   - Si el buzón es de tu empresa y tienes un dominio de Google Workspace (`camarapereira.org.co`), elige **Interno**.
   - Si no, elige **Externo** (funciona, pero con límite de 100 usuarios de prueba mientras esté en revisión).
3. Clic en **Crear**.
4. Rellena:
   - Nombre de la aplicación: `Radicados PQRSF`
   - Correo de asistencia: `jvergara@camarapereira.org.co`
   - Correo del desarrollador: el mismo.
5. Siguiente → **Agregar o quitar permisos**.
6. Busca y agrega estos dos scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.modify`
7. Siguiente → agrega tu correo como usuario de prueba (si es Externo) → Guardar y continuar.

## 4. Crear las credenciales OAuth

1. Menú ☰ → **APIs y servicios** → **Credenciales**.
2. **+ Crear credenciales** → **ID de cliente de OAuth**.
3. Tipo de aplicación: **Aplicación de escritorio**.
4. Nombre: `radicados-local`.
5. Clic en **Crear**.
6. En el diálogo que aparece, clic en **DESCARGAR JSON**.

## 7. Guardar el archivo

Guarda el JSON descargado exactamente en esta ruta:

```
C:\Users\jvergara\Desktop\RadicadosPQRSF\credentials\gmail_oauth_client.json
```

El nombre original es algo como `client_secret_1234-abc.apps.googleusercontent.com.json`; **renómbralo** a `gmail_oauth_client.json`.

## 8. Verificar que funciona

En PowerShell, dentro de la carpeta del proyecto:

```powershell
cd C:\Users\jvergara\Desktop\RadicadosPQRSF
.venv\Scripts\python.exe scripts\verificar_gmail.py
```

Se abrirá el navegador. Inicia sesión con **`unidadcorrespondencia@camarapereira.org.co`**, acepta los permisos y el script te mostrará los últimos correos de ese buzón.

> ⚠️ Ese archivo JSON contiene credenciales: **no lo subas al repositorio** ni lo envíes por chat. Está en `.gitignore`.

---

## ¿Qué hace cada permiso?

| Permiso | Para qué |
|---|---|
| `gmail.readonly` | Leer correos y adjuntos |
| `gmail.modify` | Poner la etiqueta `Radicado` al correo ya procesado |

---

¿En qué paso te trabas? Dime y seguimos.