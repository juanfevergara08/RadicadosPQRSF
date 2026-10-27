"""Extrae un correo de Gmail y guarda sus adjuntos en disco.

    python scripts/extraer_correo_prueba.py --buscar "Solicitud factura electronica"

Se usa para preparar la prueba de carga de adjuntos en DocxFlow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402
from radicados.gmail_client import ClienteGmail, ErrorAutenticacion  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "adjuntos"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buscar", default="Solicitud factura electronica")
    parser.add_argument("--limite", type=int, default=10)
    argumentos = parser.parse_args()

    config = Configuracion.cargar()
    gmail = ClienteGmail(config)

    candidatos = [
        f'subject:"{argumentos.buscar}" has:attachment',
        f'subject:"{argumentos.buscar}"',
        f"subject:factura has:attachment",
    ]

    ids: list[str] = []
    for consulta in candidatos:
        try:
            encontrados = (
                gmail.servicio.users()
                .messages()
                .list(
                    userId=config.gmail_mailbox,
                    maxResults=argumentos.limite,
                    q=consulta,
                )
                .execute()
            )
            ids = [m["id"] for m in encontrados.get("messages", [])]
        except Exception as error:  # noqa: BLE001
            print(f"[aviso] consulta {consulta!r}: {error}")
            ids = []

        print(f"consulta {consulta!r} -> {len(ids)} resultados")
        if ids:
            print(f"   usando: {consulta}")
            break

    if not ids:
        print("\nNo se encontró el correo. Revisa el asunto exacto.")
        return 1

    SALIDA.mkdir(parents=True, exist_ok=True)

    for indice, gmail_id in enumerate(ids[:3], start=1):
        correo = gmail.obtener_correo(gmail_id, descargar_adjuntos=True)
        print(f"\n[{indice}] {correo.asunto}")
        print(f"    de: {correo.remitente_nombre} <{correo.remitente_email}>")
        print(f"    cuerpo ({len(correo.cuerpo)} caracteres):")
        print("    " + correo.cuerpo[:400].replace("\n", "\n    "))

        archivo_cuerpo = SALIDA / "cuerpo_correo.txt"
        archivo_cuerpo.write_text(correo.cuerpo, encoding="utf-8")
        print(f"    cuerpo guardado: {archivo_cuerpo}")

        if not correo.adjuntos:
            print("    (sin adjuntos)")
            continue

        for adjunto in correo.adjuntos:
            if not adjunto.contenido:
                print(f"    [aviso] {adjunto.nombre} sin contenido descargado")
                continue
            nombre_seguro = "".join(
                c if c.isalnum() or c in "._-" else "_" for c in adjunto.nombre
            )
            destino = SALIDA / nombre_seguro
            destino.write_bytes(adjunto.contenido)
            print(f"    guardado: {destino} ({len(adjunto.contenido)} bytes)")

        if argumentos.limite and indice == 1:
            break

    print(f"\nArchivos en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
