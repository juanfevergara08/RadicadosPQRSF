"""Parseo de mensajes de Gmail a nuestro modelo `Correo`.

Separado del cliente HTTP a propósito: así se puede probar con payloads de
ejemplo, sin red ni credenciales.

Un correo de Gmail llega como un árbol de partes MIME:

    multipart/mixed
    ├── multipart/alternative
    │   ├── text/plain          <- lo preferimos
    │   └── text/html           <- respaldo, se convierte a texto
    ├── application/pdf   factura.pdf
    └── image/jpeg        foto.jpg
"""

from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from .models import Adjunto

# Etiquetas HTML que representan un salto de línea real
_SALTO = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h[1-6])\s*/?\s*>", re.IGNORECASE)
_BLOQUES = re.compile(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_ETIQUETAS = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"[ \t\xa0]+")
_LINEAS_VACIAS = re.compile(r"\n{3,}")


def decodificar_b64url(datos: str) -> bytes:
    """Gmail usa base64url sin relleno."""
    if not datos:
        return b""
    relleno = "=" * (-len(datos) % 4)
    return base64.urlsafe_b64decode(datos + relleno)


def html_a_texto(markup: str) -> str:
    """Convierte HTML a texto legible sin dependencias externas."""
    if not markup:
        return ""
    texto = _BLOQUES.sub(" ", markup)
    texto = _SALTO.sub("\n", texto)
    texto = _ETIQUETAS.sub(" ", texto)
    texto = html.unescape(texto)
    texto = _ESPACIOS.sub(" ", texto)
    texto = "\n".join(linea.strip() for linea in texto.splitlines())
    texto = _LINEAS_VACIAS.sub("\n\n", texto)
    return texto.strip()


def parsear_remitente(valor: str) -> tuple[str, str]:
    """De 'Juan Pérez <juan@x.com>' devuelve ('Juan Pérez', 'juan@x.com')."""
    nombre, correo = parseaddr(valor or "")
    return nombre.strip(), correo.strip().lower()


def leer_cabeceras(payload: dict) -> dict[str, str]:
    """Convierte la lista de headers de Gmail en un diccionario."""
    return {
        cabecera.get("name", "").lower(): cabecera.get("value", "")
        for cabecera in payload.get("headers", [])
    }


def parsear_fecha(valor: str) -> Optional[datetime]:
    if not valor:
        return None
    try:
        fecha = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha


def _recorrer(
    parte: dict,
    textos: list[tuple[str, str]],
    adjuntos: list[Adjunto],
    clasificacion_anexo: str,
) -> None:
    mime = (parte.get("mimeType") or "").lower()
    cuerpo = parte.get("body") or {}
    nombre = (parte.get("filename") or "").strip()

    if nombre:
        # Es un adjunto: no se recorre su contenido como cuerpo
        adjuntos.append(
            Adjunto(
                nombre=nombre,
                tipo_mime=mime or "application/octet-stream",
                tamano_bytes=int(cuerpo.get("size") or 0),
                clasificacion=clasificacion_anexo,
                contenido=None,
            )
        )
        return

    if mime.startswith("multipart/"):
        for sub_parte in parte.get("parts") or []:
            _recorrer(sub_parte, textos, adjuntos, clasificacion_anexo)
        return

    datos = cuerpo.get("data")
    if not datos:
        return

    if mime == "text/plain":
        textos.append(("plain", decodificar_b64url(datos).decode("utf-8", "replace")))
    elif mime == "text/html":
        textos.append(("html", decodificar_b64url(datos).decode("utf-8", "replace")))


def extraer_cuerpo(payload: dict) -> str:
    """Prefiere text/plain; si no hay, convierte el HTML."""
    textos: list[tuple[str, str]] = []
    adjuntos: list[Adjunto] = []
    _recorrer(payload, textos, adjuntos, "anexo")

    for tipo, contenido in textos:
        if tipo == "plain" and contenido.strip():
            return contenido.strip()

    for tipo, contenido in textos:
        if tipo == "html" and contenido.strip():
            return html_a_texto(contenido)

    return ""


def extraer_adjuntos(payload: dict, clasificacion: str = "anexo") -> list[Adjunto]:
    textos: list[tuple[str, str]] = []
    adjuntos: list[Adjunto] = []
    _recorrer(payload, textos, adjuntos, clasificacion)
    return adjuntos


def ids_de_adjuntos(payload: dict) -> list[tuple[str, str]]:
    """Devuelve [(nombre, attachmentId)] para poder descargarlos."""
    encontrados: list[tuple[str, str]] = []

    def recorrer(parte: dict) -> None:
        nombre = (parte.get("filename") or "").strip()
        cuerpo = parte.get("body") or {}
        if nombre and cuerpo.get("attachmentId"):
            encontrados.append((nombre, cuerpo["attachmentId"]))
        for sub in parte.get("parts") or []:
            recorrer(sub)

    recorrer(payload)
    return encontrados
