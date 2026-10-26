"""Orquestación: el recorrido de un correo por todas las fases.

    registrar -> ¿ya radicado? -> clasificar -> ¿confianza suficiente?
                                                  |-- no --> REVISION (humano)
                                                  |-- sí --> SGD
                                                              |-- ok ----> RADICADO
                                                              |-- error -> FALLIDO

Todo lo que no termina en RADICADO aparece en el Excel diario.
"""

from __future__ import annotations

import logging

from .classify import ClasificadorHibrido
from .models import Correo, EstadoProceso, TipoPQRSF
from .radicar import ClienteSGD
from .state import AlmacenEstado

registro = logging.getLogger(__name__)


class Procesador:
    def __init__(
        self,
        almacen: AlmacenEstado,
        clasificador: ClasificadorHibrido,
        cliente: ClienteSGD,
        umbral: float = 0.75,
    ) -> None:
        self.almacen = almacen
        self.clasificador = clasificador
        self.cliente = cliente
        self.umbral = umbral

    def procesar(self, correo: Correo) -> EstadoProceso:
        self.almacen.registrar(correo)

        permitido, motivo = self.almacen.puede_radicar(correo.message_id)
        if not permitido:
            registro.info("Omitido %s: %s", correo.message_id, motivo)
            return EstadoProceso.RADICADO

        clasificacion = self.clasificador.clasificar(correo)

        if (
            clasificacion.tipo is TipoPQRSF.DESCONOCIDO
            or clasificacion.confianza < self.umbral
        ):
            motivo_revision = (
                f"confianza {clasificacion.confianza:.2f} < umbral {self.umbral:.2f}. "
                f"{clasificacion.motivo}"
            )
            self.almacen.marcar_revision(
                correo.message_id,
                tipo=clasificacion.tipo.value,
                area=clasificacion.area,
                confianza=clasificacion.confianza,
                motivo=motivo_revision,
            )
            registro.info(
                "A revisión %s (%s)", correo.message_id, clasificacion.confianza
            )
            return EstadoProceso.REVISION

        resultado = self.cliente.crear_radicado(correo, clasificacion)

        if resultado.ok and resultado.radicado:
            self.almacen.marcar_radicado(
                correo.message_id,
                numero_radicado=resultado.radicado.numero,
                tipo=clasificacion.tipo.value,
                area=clasificacion.area,
                confianza=clasificacion.confianza,
            )
            registro.info(
                "Radicado %s -> %s", correo.message_id, resultado.radicado.numero
            )
            return EstadoProceso.RADICADO

        self.almacen.marcar_fallido(
            correo.message_id, resultado.error_codigo, resultado.error_detalle
        )
        registro.warning(
            "Falló %s: %s %s",
            correo.message_id,
            resultado.error_codigo,
            resultado.error_detalle,
        )
        return EstadoProceso.FALLIDO
