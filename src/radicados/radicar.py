"""Cliente del Sistema de Gestión Documental.

Implementa el contrato de `contracts/radicacion.openapi.yaml`. Hoy apunta al
mock local; cuando exista el SGD real solo cambia `SGD_BASE_URL`, o se ajusta
este archivo si el proveedor difiere del contrato.

La cabecera `Idempotency-Key` es obligatoria: es la segunda barrera contra
radicados duplicados.
"""

from __future__ import annotations

import base64
from typing import Optional

import requests

from . import __version__
from .models import Clasificacion, Correo, Radicado, ResultadoRadicacion


class ClienteSGD:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: int = 20,
        sesion: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.sesion = sesion or requests.Session()

    def _cabeceras(self) -> dict[str, str]:
        cabeceras = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"RadicadosPQRSF/{__version__}",
        }
        if self.token:
            cabeceras["Authorization"] = f"Bearer {self.token}"
        return cabeceras

    def listar_areas(self) -> list[dict]:
        respuesta = self.sesion.get(
            f"{self.base_url}/areas",
            headers=self._cabeceras(),
            timeout=self.timeout,
        )
        respuesta.raise_for_status()
        return respuesta.json()

    def crear_radicado(
        self, correo: Correo, clasificacion: Clasificacion
    ) -> ResultadoRadicacion:
        cuerpo = self._construir_cuerpo(correo, clasificacion)
        cabeceras = self._cabeceras()
        cabeceras["Idempotency-Key"] = correo.message_id

        try:
            respuesta = self.sesion.post(
                f"{self.base_url}/radicados",
                json=cuerpo,
                headers=cabeceras,
                timeout=self.timeout,
            )
        except requests.Timeout:
            return ResultadoRadicacion(
                ok=False,
                error_codigo="TIMEOUT",
                error_detalle="El SGD no respondió a tiempo",
                reintentable=True,
            )
        except requests.RequestException as error:
            return ResultadoRadicacion(
                ok=False,
                error_codigo="CONEXION",
                error_detalle=str(error),
                reintentable=True,
            )

        return self._interpretar(respuesta)

    def _interpretar(self, respuesta: requests.Response) -> ResultadoRadicacion:
        if respuesta.status_code in (200, 201):
            datos = respuesta.json()
            return ResultadoRadicacion(
                ok=True,
                radicado=Radicado(
                    numero=datos.get("numero", ""),
                    estado=datos.get("estado", "radicado"),
                    area_asignada=datos.get("area_asignada", ""),
                    usuario_asignado=datos.get("usuario_asignado", ""),
                ),
            )

        if respuesta.status_code == 409:
            # El SGD conoce el Message-ID: ya estaba radicado.
            datos = respuesta.json()
            numero = datos.get("numero") or datos.get("detalle", "")
            return ResultadoRadicacion(
                ok=True,
                radicado=Radicado(numero=numero, estado="radicado"),
            )

        try:
            datos = respuesta.json()
        except ValueError:
            datos = {}

        codigo = datos.get("codigo", f"HTTP_{respuesta.status_code}")
        mensaje = datos.get("mensaje") or respuesta.text[:300]

        return ResultadoRadicacion(
            ok=False,
            error_codigo=codigo,
            error_detalle=mensaje,
            reintentable=respuesta.status_code >= 500,
        )

    @staticmethod
    def _construir_cuerpo(correo: Correo, clasificacion: Clasificacion) -> dict:
        adjuntos = []
        for adjunto in correo.adjuntos:
            item = {
                "nombre": adjunto.nombre,
                "tipo_mime": adjunto.tipo_mime,
                "tamano_bytes": adjunto.tamano_bytes,
            }
            if adjunto.contenido:
                item["contenido_base64"] = base64.b64encode(
                    adjunto.contenido
                ).decode("ascii")
            adjuntos.append(item)

        return {
            "tipo": clasificacion.tipo.value,
            "asunto": correo.asunto[:500],
            "remitente": {
                "email": correo.remitente_email,
                "nombre": correo.remitente_nombre,
            },
            "cuerpo": correo.cuerpo,
            "recibido_en": correo.recibido_en.isoformat() if correo.recibido_en else None,
            "area_sugerida": clasificacion.area,
            "confianza": clasificacion.confianza,
            "adjuntos": adjuntos,
        }
