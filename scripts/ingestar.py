"""Fase 1: leer correos reales y clasificarlos. SIN radicar nada.

    python scripts/ingestar.py --limite 10
    python scripts/ingestar.py --limite 5 --guardar --etiquetar

Qué hace:
  - Lista los correos que cumplen GMAIL_QUERY
  - Descarga cuerpo, remitente y adjuntos
  - Los pasa por el clasificador y muestra el resultado
  - Opcionalmente guarda el JSON en var/correos/ y etiqueta el correo

Qué NO hace: no toca DocxFlow. Es imposible que cree un radicado.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.classify import (  # noqa: E402
    ClasificadorHibrido,
    ClasificadorReglas,
    esta_excluido,
)
from radicados.config import cargar_catalogo_areas, Configuracion  # noqa: E402
from radicados.gmail_client import ClienteGmail, ErrorAutenticacion  # noqa: E402
from radicados.models import Correo  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def correo_a_dict(
    correo: Correo, clasificacion, umbral: float, motivo_exclusion: str = ""
) -> dict:
    """Serializa sin el contenido binario de los adjuntos."""
    return {
        "message_id": correo.message_id,
        "thread_id": correo.thread_id,
        "remitente": {
            "email": correo.remitente_email,
            "nombre": correo.remitente_nombre,
        },
        "asunto": correo.asunto,
        "recibido_en": correo.recibido_en.isoformat() if correo.recibido_en else None,
        "cuerpo": correo.cuerpo,
        "adjuntos": [
            {
                "nombre": a.nombre,
                "tipo_mime": a.tipo_mime,
                "tamano_bytes": a.tamano_bytes,
                "clasificacion": a.clasificacion,
                "descargado": a.contenido is not None,
            }
            for a in correo.adjuntos
        ],
        "clasificacion": {
            "tipo": clasificacion.tipo.value,
            "area": clasificacion.area,
            "confianza": clasificacion.confianza,
            "origen": clasificacion.origen,
            "motivo": clasificacion.motivo,
            "decide_radicar": clasificacion.confianza >= umbral,
        },
        "no_es_pqrsf": motivo_exclusion,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fase 1: leer y clasificar correos")
    parser.add_argument("--limite", type=int, default=10, help="cuántos correos leer")
    parser.add_argument(
        "--sin-adjuntos", action="store_true", help="no descargar el contenido de adjuntos"
    )
    parser.add_argument(
        "--etiquetar", action="store_true", help="aplicar la etiqueta PQRSF-Leido"
    )
    parser.add_argument(
        "--guardar", action="store_true", help="guardar el JSON en var/correos/"
    )
    argumentos = parser.parse_args()

    config = Configuracion.cargar()
    catalogo = cargar_catalogo_areas(config.ruta(config.areas_config_file))
    clasificacion_anexo = catalogo.get("clasificacion_anexo_por_defecto", "anexo")

    clasificador = ClasificadorHibrido(
        reglas=ClasificadorReglas(catalogo), umbral=config.umbral_confianza
    )

    print("=" * 96)
    print("FASE 1 — Lectura de correos (no se radica nada)")
    print(f"Buzón:  {config.gmail_mailbox}")
    print(f"Filtro: {config.gmail_query}")
    print("=" * 96)

    try:
        gmail = ClienteGmail(config)
        ids = gmail.listar_pendientes(limite=argumentos.limite)
    except ErrorAutenticacion as error:
        print(f"\n[ERROR] {error}")
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"\n[ERROR] No se pudo conectar a Gmail: {error}")
        return 1

    if not ids:
        print("\nNo hay correos que cumplan el filtro. Prueba ajustando GMAIL_QUERY.")
        return 0

    print(f"\nEncontrados {len(ids)} correos.\n")

    salida = RAIZ / "var" / "correos"
    if argumentos.guardar:
        salida.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    guardados: list[dict] = []

    for indice, gmail_id in enumerate(ids, start=1):
        try:
            correo = gmail.obtener_correo(
                gmail_id,
                descargar_adjuntos=not argumentos.sin_adjuntos,
                clasificacion_anexo=clasificacion_anexo,
            )
        except Exception as error:  # noqa: BLE001
            print(f"[{indice}] ERROR leyendo {gmail_id}: {error}")
            continue

        clasificacion = clasificador.clasificar(correo)
        motivo_exclusion = esta_excluido(correo, catalogo.get("excluir"))

        if motivo_exclusion:
            ruta = "IGNORAR"
        elif clasificacion.confianza >= config.umbral_confianza:
            ruta = "RADICAR"
        else:
            ruta = "REVISAR"

        print(f"[{indice}] {correo.asunto[:64]}")
        print(f"    de:      {correo.remitente_nombre or '(sin nombre)'} "
              f"<{correo.remitente_email}>")
        print(f"    fecha:   {correo.recibido_en or '(sin fecha)'}")
        if motivo_exclusion:
            print(f"    no es PQRSF -> {motivo_exclusion}")
        else:
            print(f"    tipo:    {clasificacion.tipo.value:13} area: {clasificacion.area}")
            print(f"    conf:    {clasificacion.confianza:.2f}  -> {ruta}")
        print(f"    cuerpo:  {len(correo.cuerpo)} caracteres")
        if correo.adjuntos:
            for adjunto in correo.adjuntos:
                descargado = f"{adjunto.tamano_bytes} B" if adjunto.contenido else "no descargado"
                print(f"    anexo:   {adjunto.nombre} ({adjunto.tipo_mime}, {descargado}) "
                      f"-> {adjunto.clasificacion}")
        print()

        if argumentos.guardar:
            guardados.append(
                correo_a_dict(
                    correo, clasificacion, config.umbral_confianza, motivo_exclusion
                )
            )

        if argumentos.etiquetar:
            try:
                gmail.aplicar_etiqueta(gmail_id, config.gmail_label_leido)
                print(f"    etiqueta aplicada: {config.gmail_label_leido}\n")
            except Exception as error:  # noqa: BLE001
                print(f"    [AVISO] no se pudo etiquetar: {error}\n")

    if argumentos.guardar and guardados:
        archivo = salida / f"correos_{marca}.json"
        archivo.write_text(
            json.dumps(guardados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Guardado: {archivo}")

    print("\nFase 1 completa. No se creó ningún radicado.")
    print("Revisa los correos en REVISAR: son los que el clasificador no resuelve solo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
