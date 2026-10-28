"""Pruebas de la comparación de nombres Gmail <-> DocxFlow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.nombres import coincide, normalizar, prefijo_de  # noqa: E402


class PruebasNormalizar(unittest.TestCase):
    def test_quita_tildes_simbolos_y_mayusculas(self) -> None:
        self.assertEqual(normalizar("Comprobante transacción.pdf"), "comprobantetransaccionpdf")

    def test_espacios_y_guiones_desaparecen(self) -> None:
        self.assertEqual(normalizar("RUT_Genera S.A.S.pdf"), "rutgenerasaspdf")


class PruebasPrefijo(unittest.TestCase):
    def test_gmail_y_docxflow_comparten_prefijo(self) -> None:
        """El caso real: DocxFlow reemplaza la tilde por guion bajo."""
        original = "Comprobante transacción.pdf"
        renombrado = "Comprobante_transacci_n_980291.pdf"
        self.assertEqual(prefijo_de(original), prefijo_de(renombrado))

    def test_nombre_con_puntos_no_rompe(self) -> None:
        self.assertEqual(
            prefijo_de("RUT_Genera_SAS_ESP_19_ENE_2026.pdf"),
            prefijo_de("RUT_Genera_SAS_ESP_19_ENE_2026_931404.pdf"),
        )


class PruebasCoincide(unittest.TestCase):
    def test_encuentra_la_fila_correcta(self) -> None:
        fila = "Comprobante_transacci_n_980291.pdf\t2\t2\tElectrónico\tNo\tAnexos"
        self.assertTrue(coincide("Comprobante transacción.pdf", fila))

    def test_no_confunde_con_otro_documento(self) -> None:
        fila = "Comprobante_transacci_n_725408.pdf\t2\t2\tElectrónico\tSi\tAnexos"
        self.assertFalse(coincide("RUT_Genera_SAS_ESP_19_ENE_2026.pdf", fila))

    def test_nombre_vacio_nunca_coincide(self) -> None:
        self.assertFalse(coincide("", "cualquier texto"))


if __name__ == "__main__":
    unittest.main()
