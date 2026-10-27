"""Pruebas del parseo de mensajes de Gmail.

Usan payloads con la misma forma que devuelve la API, sin red ni credenciales.
"""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.correo_parser import (  # noqa: E402
    decodificar_b64url,
    extraer_adjuntos,
    extraer_cuerpo,
    html_a_texto,
    ids_de_adjuntos,
    leer_cabeceras,
    parsear_fecha,
    parsear_remitente,
)


def b64(texto: str) -> str:
    """Codifica como Gmail: base64url sin relleno."""
    return base64.urlsafe_b64encode(texto.encode("utf-8")).decode("ascii").rstrip("=")


def payload_multipart() -> dict:
    return {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Ana María Ríos <Ana.Rios@Example.com>"},
            {"name": "Subject", "value": "Solicitud de información"},
            {"name": "Message-ID", "value": "<abc123@mail.gmail.com>"},
            {"name": "Date", "value": "Mon, 26 Oct 2026 10:30:00 -0500"},
        ],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": b64("Hola, solicito información.")}},
                    {
                        "mimeType": "text/html",
                        "body": {"data": b64("<p>Hola, <b>solicito</b> información.</p>")},
                    },
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "cedula.pdf",
                "body": {"size": 48213, "attachmentId": "att-1"},
            },
            {
                "mimeType": "image/jpeg",
                "filename": "foto.jpg",
                "body": {"size": 9200, "attachmentId": "att-2"},
            },
        ],
    }


class PruebasDecodificacion(unittest.TestCase):
    def test_b64url_sin_relleno(self) -> None:
        self.assertEqual(decodificar_b64url(b64("abc")), b"abc")

    def test_b64url_vacio(self) -> None:
        self.assertEqual(decodificar_b64url(""), b"")


class PruebasHtmlATexto(unittest.TestCase):
    def test_quita_etiquetas(self) -> None:
        self.assertEqual(html_a_texto("<p>Hola <b>mundo</b></p>"), "Hola mundo")

    def test_conserva_saltos_de_parrafo(self) -> None:
        texto = html_a_texto("<p>Linea uno</p><p>Linea dos</p>")
        self.assertIn("Linea uno", texto)
        self.assertIn("Linea dos", texto)
        self.assertGreaterEqual(texto.count("\n"), 1)

    def test_elimina_script_y_style(self) -> None:
        texto = html_a_texto(
            "<style>p{color:red}</style><script>alert('x')</script><p>Real</p>"
        )
        self.assertEqual(texto, "Real")

    def test_decodifica_entidades(self) -> None:
        self.assertIn("ñ", html_a_texto("<p>Se&ntilde;or</p>"))


class PruebasRemitente(unittest.TestCase):
    def test_nombre_y_correo(self) -> None:
        nombre, correo = parsear_remitente("Ana María Ríos <Ana.Rios@Example.com>")
        self.assertEqual(nombre, "Ana María Ríos")
        self.assertEqual(correo, "ana.rios@example.com")

    def test_solo_correo(self) -> None:
        nombre, correo = parsear_remitente("solo@correo.com")
        self.assertEqual(nombre, "")
        self.assertEqual(correo, "solo@correo.com")

    def test_vacio_no_falla(self) -> None:
        self.assertEqual(parsear_remitente(""), ("", ""))


class PruebasFechas(unittest.TestCase):
    def test_parsea_con_zona(self) -> None:
        fecha = parsear_fecha("Mon, 26 Oct 2026 10:30:00 -0500")
        self.assertIsNotNone(fecha)
        self.assertEqual(fecha.year, 2026)

    def test_fecha_invalida_devuelve_none(self) -> None:
        self.assertIsNone(parsear_fecha("no es una fecha"))


class PruebasCuerpoYAdjuntos(unittest.TestCase):
    def test_cabeceras_en_minuscula(self) -> None:
        cabeceras = leer_cabeceras(payload_multipart())
        self.assertEqual(cabeceras["subject"], "Solicitud de información")

    def test_prefiere_text_plain(self) -> None:
        self.assertEqual(extraer_cuerpo(payload_multipart()), "Hola, solicito información.")

    def test_usa_html_si_no_hay_plain(self) -> None:
        payload = {
            "mimeType": "text/html",
            "body": {"data": b64("<p>Solo <b>HTML</b></p>")},
        }
        self.assertEqual(extraer_cuerpo(payload), "Solo HTML")

    def test_detecta_adjuntos_anidados(self) -> None:
        adjuntos = extraer_adjuntos(payload_multipart(), clasificacion="anexo")
        nombres = [a.nombre for a in adjuntos]
        self.assertEqual(nombres, ["cedula.pdf", "foto.jpg"])
        self.assertTrue(all(a.clasificacion == "anexo" for a in adjuntos))
        self.assertEqual(adjuntos[0].tamano_bytes, 48213)

    def test_ids_de_adjuntos(self) -> None:
        self.assertEqual(
            ids_de_adjuntos(payload_multipart()),
            [("cedula.pdf", "att-1"), ("foto.jpg", "att-2")],
        )

    def test_payload_sin_cuerpo_devuelve_vacio(self) -> None:
        self.assertEqual(extraer_cuerpo({"mimeType": "multipart/mixed"}), "")


if __name__ == "__main__":
    unittest.main()
