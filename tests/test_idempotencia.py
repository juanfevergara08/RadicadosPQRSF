"""Prueba de integración: end-to-end contra el mock de DocxFlow.

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
from radicados.models import Clasificacion, Correo, EstadoProceso, TipoPQRSF  # noqa: E402
from radicados.proceso import Procesador  # noqa: E402
from radicados.radicar import ClienteSGD, validar_numero_radicado  # noqa: E402
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


class PruebasValidacionRadicado(unittest.TestCase):
    def test_formato_ccpe_valido(self) -> None:
        self.assertTrue(validar_numero_radicado("CCPE26-0001")[0])
        self.assertTrue(validar_numero_radicado("CCPE27-1234", anio=2027)[0])

    def test_rechaza_formatos_incorrectos(self) -> None:
        for numero in ["CCPE-26-0001", "CCP26-0001", "CCPE26-1", "PQRSF-2026-0001", ""]:
            with self.subTest(numero=numero):
                self.assertFalse(validar_numero_radicado(numero)[0])

    def test_rechaza_anio_que_no_corresponde(self) -> None:
        valido, motivo = validar_numero_radicado("CCPE26-0001", anio=2027)
        self.assertFalse(valido)
        self.assertIn("CCPE27", motivo)


class PruebasIntegracionDocxFlow(unittest.TestCase):
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
        self.catalogo = cargar_catalogo_areas(RAIZ / "config" / "areas.yaml")
        self.cliente = ClienteSGD(
            base_url=self.base_url, timeout=5, catalogo=self.catalogo
        )
        self.procesador = Procesador(
            self.almacen,
            ClasificadorHibrido(
                ClasificadorReglas(self.catalogo), umbral=UMBRAL
            ),
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
        radicados = self._radicados_en_mock()
        self.assertEqual(len(radicados), 1)
        self.assertTrue(validar_numero_radicado(radicados[0]["numero"])[0])

    def test_procesar_dos_veces_crea_un_solo_radicado(self) -> None:
        self.procesador.procesar(CORREO_CLARO)
        self.procesador.procesar(CORREO_CLARO)

        self.assertEqual(len(self._radicados_en_mock()), 1)

    def test_el_sgd_tambien_es_idempotente_por_su_cuenta(self) -> None:
        """Aunque el estado local se pierda, el SGD no duplica."""
        clasificacion = Clasificacion(
            tipo=TipoPQRSF.RECLAMO, area="financiera", confianza=0.9
        )

        primero = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)
        segundo = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)

        self.assertTrue(primero.ok)
        self.assertTrue(segundo.ok)
        self.assertEqual(primero.radicado.numero, segundo.radicado.numero)
        self.assertEqual(len(self._radicados_en_mock()), 1)

    def test_todos_los_tipos_pqrsf_tienen_tramite_real(self) -> None:
        """El mapeo del catálogo debe apuntar a trámites que DocxFlow acepta."""
        from mock.sgd_mock import TRAMITES

        codigos = {tramite["codigo"] for tramite in TRAMITES}
        mapa = self.catalogo["tramites"]
        for tipo in ("peticion", "queja", "reclamo", "sugerencia", "felicitacion"):
            with self.subTest(tipo=tipo):
                self.assertIn(tipo, mapa)
                self.assertIn(str(mapa[tipo]), codigos)

    def test_area_sin_destinatario_no_radica(self) -> None:
        clasificacion = Clasificacion(
            tipo=TipoPQRSF.QUEJA, area="area_que_no_existe", confianza=0.9
        )

        resultado = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error_codigo, "SIN_DESTINATARIO")
        self.assertFalse(resultado.reintentable)
        self.assertEqual(self._radicados_en_mock(), [])

    def test_tipo_sin_mapeo_de_tramite_no_radica(self) -> None:
        clasificacion = Clasificacion(
            tipo=TipoPQRSF.DESCONOCIDO, area="financiera", confianza=0.9
        )

        resultado = self.cliente.crear_radicado(CORREO_CLARO, clasificacion)

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error_codigo, "SIN_MAPEO_TRAMITE")
        self.assertEqual(self._radicados_en_mock(), [])


if __name__ == "__main__":
    unittest.main()
