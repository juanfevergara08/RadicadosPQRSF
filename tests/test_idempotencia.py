"""Prueba de integración: end-to-end contra el mock del SGD.

Es la prueba que importa. Verifica que procesar el mismo correo dos veces
produce UN solo radicado, tanto por la defensa local (estado) como por la
defensa del servidor (Idempotency-Key).
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))

import requests  # noqa: E402

from mock.sgd_mock import crear_servidor, reiniciar_estado  # noqa: E402
from radicados.classify import ClasificadorHibrido, ClasificadorReglas  # noqa: E402
from radicados.config import cargar_catalogo_areas  # noqa: E402
from radicados.models import Correo, EstadoProceso  # noqa: E402
from radicados.proceso import Procesador  # noqa: E402
from radicados.radicar import ClienteSGD  # noqa: E402
from radicados.state import AlmacenEstado  # noqa: E402

UMBRAL = 0.75

CORREO_CLARO = Correo(
    message_id="<idempotencia@mail.gmail.com>",
    remitente_email="cliente@example.com",
    asunto="Reclamo por cobro indebido en mi factura",
    cuerpo=(
        "Presento reclamo porque me cobraron dos veces. Solicito devolucion "
        "del dinero y correccion del cobro indebido."
    ),
)


class PruebasIntegracionSGD(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.servidor = crear_servidor(0)
        cls.base_url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self) -> None:
        reiniciar_estado()
        self._directorio = tempfile.TemporaryDirectory()
        self.almacen = AlmacenEstado(Path(self._directorio.name) / "state.db")
        self.cliente = ClienteSGD(base_url=self.base_url, timeout=5)
        catalogo = cargar_catalogo_areas(RAIZ / "config" / "areas.yaml")
        self.procesador = Procesador(
            self.almacen,
            ClasificadorHibrido(ClasificadorReglas(catalogo), umbral=UMBRAL),
            self.cliente,
            umbral=UMBRAL,
        )

    def tearDown(self) -> None:
        self._directorio.cleanup()

    def _radicados_en_mock(self) -> list[dict]:
        return requests.get(f"{self.base_url}/_debug/radicados", timeout=5).json()

    def test_correo_claro_se_radica(self) -> None:
        estado = self.procesador.procesar(CORREO_CLARO)

        self.assertIs(estado, EstadoProceso.RADICADO)
        self.assertEqual(len(self._radicados_en_mock()), 1)

    def test_procesar_dos_veces_crea_un_solo_radicado(self) -> None:
        self.procesador.procesar(CORREO_CLARO)
        self.procesador.procesar(CORREO_CLARO)

        self.assertEqual(len(self._radicados_en_mock()), 1)

    def test_el_sgd_tambien_es_idempotente_por_su_cuenta(self) -> None:
        """Aunque el estado local se pierda, el SGD no duplica."""
        from radicados.models import Clasificacion, TipoPQRSF

        clasificacion = Clasificacion(
            tipo=TipoPQRSF.RECLAMO, area="financiera", confianza=0.9
        )

        primero = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)
        segundo = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)

        self.assertTrue(primero.ok)
        self.assertTrue(segundo.ok)
        self.assertEqual(primero.radicado.numero, segundo.radicado.numero)
        self.assertEqual(len(self._radicados_en_mock()), 1)

    def test_area_inexistente_produce_fallido_no_excepcion(self) -> None:
        from radicados.models import Clasificacion, TipoPQRSF

        clasificacion = Clasificacion(
            tipo=TipoPQRSF.QUEJA, area="area_que_no_existe", confianza=0.9
        )

        resultado = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error_codigo, "AREA_INEXISTENTE")
        self.assertEqual(self._radicados_en_mock(), [])


if __name__ == "__main__":
    unittest.main()
