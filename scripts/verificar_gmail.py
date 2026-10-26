"""Verifica que la configuración de Google Cloud quedó bien.

    python scripts/verificar_gmail.py

Hace tres cosas:
  1. Comprueba que el archivo de credenciales OAuth existe.
  2. Abre el navegador para que autorices (solo la primera vez).
  3. Lista los últimos correos del buzón configurado.

No modifica nada en Gmail: solo lee.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main() -> int:
    config = Configuracion.cargar()
    ruta_credenciales = config.ruta(config.gmail_credentials_file)
    ruta_token = config.ruta(config.gmail_token_file)

    print(f"Buzón configurado: {config.gmail_mailbox}")

    if not ruta_credenciales.exists():
        print("\n[ERROR] No existe el archivo de credenciales:")
        print(f"        {ruta_credenciales}")
        print("\nDescárgalo de Google Cloud Console:")
        print("  APIs y servicios > Credenciales > tu OAuth Client ID > Descargar JSON")
        print(f"  y guárdalo exactamente en esa ruta.")
        return 1

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("\n[ERROR] Faltan dependencias. Ejecuta:")
        print("        pip install -r requirements.txt")
        return 1

    credenciales = None
    if ruta_token.exists():
        credenciales = Credentials.from_authorized_user_file(str(ruta_token), SCOPES)

    if not credenciales or not credenciales.valid:
        if credenciales and credenciales.expired and credenciales.refresh_token:
            credenciales.refresh(Request())
        else:
            print("\nSe abrirá el navegador para autorizar el acceso.")
            print("Inicia sesión con la cuenta del buzón y acepta los permisos.\n")
            flujo = InstalledAppFlow.from_client_secrets_file(
                str(ruta_credenciales), SCOPES
            )
            credenciales = flujo.run_local_server(port=0)

        ruta_token.parent.mkdir(parents=True, exist_ok=True)
        ruta_token.write_text(credenciales.to_json(), encoding="utf-8")
        print(f"\nToken guardado en {ruta_token}")

    servicio = build("gmail", "v1", credentials=credenciales)

    perfil = servicio.users().getProfile(userId="me").execute()
    print(f"\n[OK] Autenticado como: {perfil.get('emailAddress')}")
    print(f"     Mensajes en el buzón: {perfil.get('messagesTotal')}")

    resultado = (
        servicio.users()
        .messages()
        .list(userId="me", maxResults=5, q=config.gmail_query)
        .execute()
    )
    mensajes = resultado.get("messages", [])

    print(f"\nÚltimos {len(mensajes)} correos que cumplen: {config.gmail_query!r}\n")
    for item in mensajes:
        detalle = (
            servicio.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        cabeceras = {
            c["name"]: c["value"] for c in detalle.get("payload", {}).get("headers", [])
        }
        print(f"  - {cabeceras.get('Subject', '(sin asunto)')[:60]}")
        print(f"    de: {cabeceras.get('From', '')[:70]}")
        print(f"    id: {item['id']}")

    print("\nLa configuración de Google Cloud funciona correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
