"""Extrae el correo de Frisby y deja los 3 adjuntos con nombres limpios.

    python scripts/extraer_frisby.py --confirmar

Renombra según el contenido del nombre original para que el mapeo sea
determinista y no dependa de tildes ni espacios:

    01_solicitud_devolucion.pdf
    02_cedula.pdf
    03_certificacion_bancaria.pdf
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion
from radicados.gmail_client import ClienteGmail

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "adjuntos"

REGLAS = [
    ("devolu", "01_solicitud_devolucion.pdf"),
    ("apoderada", "02_cedula.pdf"),
    ("cedula", "02_cedula.pdf"),
    ("bancolombia", "03_certificacion_bancaria.pdf"),
    ("certificacion", "03_certificacion_bancaria.pdf"),
]


def destino(nombre: str) -> str | None:
    bajo = nombre.lower()
    for clave, archivo in REGLAS:
        if clave in bajo:
            return archivo
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument(
        "--query", default="from:epinzon@frisby.com.co after:2026/09/17 before:2026/09/19"
    )
    args = parser.parse_args()
    if not args.confirmar:
        print("Ejecuta con --confirmar")
        return 2

    config = Configuracion.cargar()
    gmail = ClienteGmail(config)

    res = (
        gmail.servicio.users()
        .messages()
        .list(userId=config.gmail_mailbox, maxResults=5, q=args.query)
        .execute()
    )
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        print("No se encontró el correo")
        return 1

    SALIDA.mkdir(parents=True, exist_ok=True)
    for f in SALIDA.glob("*.pdf"):
        f.unlink()

    msg = (
        gmail.servicio.users()
        .messages()
        .get(userId=config.gmail_mailbox, id=ids[0], format="full")
        .execute()
    )
    payload = msg.get("payload", {})
    cabeceras = {h["name"]: h["value"] for h in payload.get("headers", [])}
    print(f"Asunto: {cabeceras.get('Subject')}")
    print(f"De:     {cabeceras.get('From')}")
    print(f"Fecha:  {cabeceras.get('Date')}")

    textos: list[str] = []
    guardados: list[Path] = []

    def recorrer(parte: dict) -> None:
        mime = parte.get("mimeType", "")
        cuerpo = parte.get("body", {})
        nombre = (parte.get("filename") or "").strip()
        datos = cuerpo.get("data")
        att_id = cuerpo.get("attachmentId")

        if nombre and att_id:
            objetivo = destino(nombre)
            if objetivo is None:
                print(f"  [omitido] {nombre} (no coincide con ninguna regla)")
            else:
                att = (
                    gmail.servicio.users()
                    .messages()
                    .attachments()
                    .get(
                        userId=config.gmail_mailbox,
                        messageId=ids[0],
                        id=att_id,
                    )
                    .execute()
                )
                contenido = base64.urlsafe_b64decode(att.get("data", "") + "==")
                ruta = SALIDA / objetivo
                ruta.write_bytes(contenido)
                guardados.append(ruta)
                print(f"  {nombre}  ->  {objetivo} ({len(contenido)} bytes)")
        elif mime == "text/plain" and datos:
            textos.append(
                base64.urlsafe_b64decode(datos + "==").decode("utf-8", errors="replace")
            )

        for sub in parte.get("parts", []):
            recorrer(sub)

    recorrer(payload)

    if textos:
        cuerpo_txt = "\n".join(textos).strip()
        (SALIDA / "cuerpo_correo.txt").write_text(cuerpo_txt, encoding="utf-8")
        print(f"\nCuerpo guardado ({len(cuerpo_txt)} caracteres)")

    print(f"\nAdjuntos listos: {len(guardados)}")
    for r in guardados:
        print(f"  - {r.name}")
    return 0 if len(guardados) == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
