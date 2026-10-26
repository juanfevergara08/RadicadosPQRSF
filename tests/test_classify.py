"""Pruebas del clasificador por reglas.

Lo que se garantiza aquí es la decisión de ruta, no el porcentaje exacto:
un correo claro debe superar el umbral, y uno ambiguo debe quedar por debajo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.classify import (  # noqa: E402
    ClasificadorReglas,
    normalizar,
)
from radicados.config import cargar_catalogo_areas  # noqa: E402
from radicados.models import Correo, TipoPQRSF  # noqa: E402

UMBRAL = 0.75


def _correo(asunto: str, cuerpo: str) -> Correo:
    return Correo(
        message_id="<test@example.com>",
        remitente_email="test@example.com",
        asunto=asunto,
        cuerpo=cuerpo,
    )


class PruebasNormalizacion(unittest.TestCase):
    def test_quita_tildes_y_mayusculas(self) -> None:
        self.assertEqual(normalizar("Petición  DE  Información"), "peticion de informacion")


class PruebasClasificadorReglas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogo = cargar_catalogo_areas(RAIZ / "config" / "areas.yaml")
        cls.reglas = ClasificadorReglas(cls.catalogo)

    def test_reclamo_de_factura_supera_el_umbral(self) -> None:
        resultado = self.reglas.clasificar(
            _correo(
                "Reclamo por cobro indebido en mi factura",
                "Presento reclamo porque me cobraron dos veces. Solicito "
                "devolucion del dinero y correccion del cobro indebido.",
            )
        )
        self.assertIs(resultado.tipo, TipoPQRSF.RECLAMO)
        self.assertEqual(resultado.area, "financiera")
        self.assertGreaterEqual(resultado.confianza, UMBRAL)
        self.assertTrue(resultado.es_confiable)

    def test_queja_por_maltrato_va_a_atencion_al_usuario(self) -> None:
        resultado = self.reglas.clasificar(
            _correo(
                "Queja por la atencion recibida",
                "Presento queja por la mala atencion y el maltrato del asesor. "
                "La atencion fue deficiente.",
            )
        )
        self.assertIs(resultado.tipo, TipoPQRSF.QUEJA)
        self.assertEqual(resultado.area, "atencion_usuario")
        self.assertGreaterEqual(resultado.confianza, UMBRAL)

    def test_sin_palabras_clave_queda_en_revision(self) -> None:
        resultado = self.reglas.clasificar(
            _correo("Consulta", "Buenas tardes, quedo atento a su respuesta.")
        )
        self.assertIs(resultado.tipo, TipoPQRSF.DESCONOCIDO)
        self.assertLess(resultado.confianza, UMBRAL)
        self.assertFalse(resultado.es_confiable)

    def test_tipo_claro_pero_area_incierta_no_se_radica(self) -> None:
        """Una petición sin área identificable NO debe radicarse sola."""
        resultado = self.reglas.clasificar(
            _correo("Solicitud", "Solicito informacion sobre el estado de mi tramite.")
        )
        self.assertIs(resultado.tipo, TipoPQRSF.PETICION)
        self.assertLess(resultado.confianza, UMBRAL)


if __name__ == "__main__":
    unittest.main()
