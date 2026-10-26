"""Demo end-to-end sin Gmail y sin SGD real.

    python run_demo.py

Levanta el mock del SGD en un puerto libre, hace pasar 4 correos de ejemplo por
todo el recorrido, fuerza un fallo, reintenta un correo ya radicado para
demostrar la idempotencia, y genera el Excel de no radicados.

No requiere credenciales de Google ni conexión a internet.
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))

from mock.sgd_mock import crear_servidor, reiniciar_estado  # noqa: E402
from radicados.classify import ClasificadorHibrido, ClasificadorReglas  # noqa: E402
from radicados.config import cargar_catalogo_areas  # noqa: E402
from radicados.models import Adjunto, Correo, EstadoProceso  # noqa: E402
from radicados.proceso import Procesador  # noqa: E402
from radicados.radicar import ClienteSGD  # noqa: E402
from radicados.report import generar_reporte  # noqa: E402
from radicados.state import AlmacenEstado  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Los avisos del proceso van a stdout, no a stderr: PowerShell trata stderr
# como error y ensucia la salida del demo.
logging.basicConfig(level=logging.WARNING, format="  · %(message)s", stream=sys.stdout)

UMBRAL = 0.75

CORREOS_DEMO = [
    Correo(
        message_id="<a1-reclamo-factura@mail.gmail.com>",
        remitente_email="cliente.molesto@example.com",
        remitente_nombre="Cliente Molesto",
        asunto="Reclamo por cobro indebido en mi factura",
        cuerpo=(
            "Buenas tardes. Presento reclamo porque me cobraron dos veces el "
            "servicio. Adjunto la factura. Solicito devolucion del dinero y "
            "correccion del cobro indebido."
        ),
        adjuntos=[
            Adjunto(
                nombre="factura_marzo.pdf",
                tipo_mime="application/pdf",
                tamano_bytes=48213,
                clasificacion="factura",
                contenido=b"%PDF-1.4 demo",
            )
        ],
        recibido_en=datetime.now(),
    ),
    Correo(
        message_id="<b2-queja-atencion@mail.gmail.com>",
        remitente_email="usuario.enojado@example.com",
        remitente_nombre="Usuario Enojado",
        asunto="Queja por la atencion recibida en la oficina",
        cuerpo=(
            "Quiero presentar una queja por la mala atencion y el maltrato "
            "recibido del asesor. La atencion fue deficiente y hubo demora en "
            "la atencion."
        ),
        recibido_en=datetime.now(),
    ),
    Correo(
        message_id="<c3-ambiguo@mail.gmail.com>",
        remitente_email="persona.dudosa@example.com",
        asunto="Consulta",
        cuerpo="Buenas tardes, necesito saber algo sobre mi caso. Quedo atento.",
        recibido_en=datetime.now(),
    ),
    Correo(
        message_id="<d4-peticion-sin-area@mail.gmail.com>",
        remitente_email="solicitante@example.com",
        asunto="Solicitud",
        cuerpo="Solicito informacion sobre el estado de mi tramite.",
        recibido_en=datetime.now(),
    ),
]

ETIQUETAS = {
    EstadoProceso.RADICADO: "RADICADO",
    EstadoProceso.REVISION: "REVISION",
    EstadoProceso.FALLIDO: "FALLIDO",
    EstadoProceso.PENDIENTE: "PENDIENTE",
}


def main() -> None:
    reiniciar_estado()

    servidor = crear_servidor(0)
    puerto = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    almacen = AlmacenEstado(RAIZ / "var" / "demo_state.db")
    # Base limpia en cada corrida del demo
    almacen.ruta.unlink(missing_ok=True)
    almacen = AlmacenEstado(RAIZ / "var" / "demo_state.db")

    catalogo = cargar_catalogo_areas(RAIZ / "config" / "areas.yaml")
    clasificador = ClasificadorHibrido(
        reglas=ClasificadorReglas(catalogo), umbral=UMBRAL, ia=None
    )
    cliente = ClienteSGD(base_url=f"http://127.0.0.1:{puerto}", catalogo=catalogo)
    procesador = Procesador(almacen, clasificador, cliente, umbral=UMBRAL)

    print("=" * 78)
    print(f"DEMO RadicadosPQRSF  |  mock SGD en http://127.0.0.1:{puerto}")
    print(f"Umbral de confianza: {UMBRAL}")
    print("=" * 78)

    print("\n[1] Correos entrantes\n")
    for correo in CORREOS_DEMO:
        estado = procesador.procesar(correo)
        clasificacion = clasificador.clasificar(correo)
        print(f"  {ETIQUETAS[estado]:9} | {correo.asunto[:44]:44} | "
              f"{clasificacion.tipo.value:12} | area={clasificacion.area:18} "
              f"| conf={clasificacion.confianza:.2f}")

    print("\n[2] El SGD se cae a mitad de proceso\n")
    cliente_caido = ClienteSGD(
        base_url="http://127.0.0.1:9", timeout=2, catalogo=catalogo
    )
    procesador_caido = Procesador(almacen, clasificador, cliente_caido, umbral=UMBRAL)
    correo_que_falla = Correo(
        message_id="<e5-sgd-caido@mail.gmail.com>",
        remitente_email="cliente.afectado@example.com",
        asunto="Reclamo por cobro indebido en la factura del servicio",
        cuerpo="Presento reclamo por el cobro indebido. Solicito devolucion.",
        recibido_en=datetime.now(),
    )
    estado = procesador_caido.procesar(correo_que_falla)
    fila = almacen.obtener(correo_que_falla.message_id)
    print(f"  {ETIQUETAS[estado]:9} | {correo_que_falla.asunto[:44]:44} "
          f"| error={fila['ultimo_error']}")

    print("\n[3] Se reprocesa el primero (ya radicado)\n")
    estado = procesador.procesar(CORREOS_DEMO[0])
    permitido, motivo = almacen.puede_radicar(CORREOS_DEMO[0].message_id)
    print(f"  {ETIQUETAS[estado]:9} | sin crear duplicado -> {motivo}")

    print("\n[4] Radicados creados en el mock\n")
    for radicado in cliente.sesion.get(
        f"http://127.0.0.1:{puerto}/_debug/radicados"
    ).json():
        print(f"  {radicado['numero']}  {radicado['tipo_tramite']:20} "
              f"dest={radicado['destinatario']:34} {radicado['asunto'][:30]}")

    ruta_reporte = generar_reporte(almacen, RAIZ / "var" / "reportes")
    print("\n[5] Reporte diario de no radicados\n")
    print(f"  {ruta_reporte}")
    print(f"  Resumen: {almacen.resumen()}")

    servidor.shutdown()
    print("\nListo. Abre el .xlsx para ver los correos en revisión y el fallido.")


if __name__ == "__main__":
    main()
