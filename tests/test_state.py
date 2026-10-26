"""Pruebas del almacén de estado: la garantía de no duplicar radicados."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.models import Correo, EstadoProceso  # noqa: E402
from radicados.state import AlmacenEstado  # noqa: E402


class PruebasAlmacenEstado(unittest.TestCase):
    def setUp(self) -> None:
        self._directorio = tempfile.TemporaryDirectory()
        self.almacen = AlmacenEstado(Path(self._directorio.name) / "state.db")
        self.correo = Correo(
            message_id="<abc@mail.gmail.com>",
            remitente_email="persona@example.com",
            asunto="Solicitud",
            cuerpo="Solicito informacion",
        )

    def tearDown(self) -> None:
        self._directorio.cleanup()

    def test_correo_nuevo_puede_radicarse(self) -> None:
        permitido, motivo = self.almacen.puede_radicar(self.correo.message_id)
        self.assertTrue(permitido)
        self.assertEqual(motivo, "correo nuevo")

    def test_un_correo_radicado_no_vuelve_a_radicarse(self) -> None:
        self.almacen.registrar(self.correo)
        self.almacen.marcar_radicado(
            self.correo.message_id,
            numero_radicado="PQRSF-2026-000001",
            tipo="peticion",
            area="atencion_usuario",
            confianza=0.9,
        )

        permitido, motivo = self.almacen.puede_radicar(self.correo.message_id)

        self.assertFalse(permitido)
        self.assertIn("PQRSF-2026-000001", motivo)

    def test_registrar_dos_veces_no_duplica_ni_pisa_el_estado(self) -> None:
        self.almacen.registrar(self.correo)
        self.almacen.marcar_radicado(
            self.correo.message_id, "PQRSF-2026-000001", "peticion", "atencion_usuario", 0.9
        )
        self.almacen.registrar(self.correo)  # segunda pasada del mismo correo

        fila = self.almacen.obtener(self.correo.message_id)

        self.assertIsNotNone(fila)
        self.assertEqual(fila["estado"], EstadoProceso.RADICADO.value)
        self.assertEqual(fila["numero_radicado"], "PQRSF-2026-000001")
        self.assertEqual(self.almacen.resumen(), {"radicado": 1})

    def test_marcar_fallido_acumula_intentos(self) -> None:
        self.almacen.registrar(self.correo)
        self.almacen.marcar_fallido(self.correo.message_id, "TIMEOUT", "sin respuesta")
        self.almacen.marcar_fallido(self.correo.message_id, "TIMEOUT", "sin respuesta")

        fila = self.almacen.obtener(self.correo.message_id)

        self.assertEqual(fila["estado"], EstadoProceso.FALLIDO.value)
        self.assertEqual(fila["intentos"], 2)
        self.assertIn("TIMEOUT", fila["ultimo_error"])

    def test_fallido_puede_reintentarse(self) -> None:
        self.almacen.registrar(self.correo)
        self.almacen.marcar_fallido(self.correo.message_id, "TIMEOUT", "sin respuesta")

        permitido, motivo = self.almacen.puede_radicar(self.correo.message_id)

        self.assertTrue(permitido)
        self.assertIn("reintento", motivo)


if __name__ == "__main__":
    unittest.main()
