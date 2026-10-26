"""Cliente del Sistema de Gestión Documental (DocxFlow).

Implementa `contracts/radicacion.openapi.yaml`.

DOS COSAS IMPORTANTES
---------------------
1. `Idempotency-Key` es obligatoria. Es la única barrera que sobrevive si se
   pierde el estado local (SQLite).

2. DocxFlow **genera** el número de radicado; aquí solo lo recibimos y
   validamos contra el patrón CCPE<AA>-<NNNN>. Si no coincide, se trata como
   fallo: un número raro en el SGD es más grave que un correo sin radicar.
"""

from __future__ import annotations

import base64
import re
from typing import Optional

import requests

from . import __version__
from .models import Clasificacion, Correo, Radicado, ResultadoRadicacion

PATRON_RADICADO = re.compile(r"^CCPE\d{2}-\d{4}$")


def validar_numero_radicado(numero: str, anio: Optional[int] = None) -> tuple[bool, str]:
    """Valida el formato CCPE<AA>-<NNNN> y que el año corresponda."""
    if not PATRON_RADICADO.match(numero or ""):
        return False, f"'{numero}' no cumple CCPE<AA>-<NNNN>"

    if anio is not None:
        esperado = f"CCPE{anio % 100:02d}-"
        if not numero.startswith(esperado):
            return False, f"'{numero}' no corresponde al año {anio} (se esperaba {esperado}NNNN)"

    return True, ""


class ClienteSGD:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: int = 20,
        catalogo: Optional[dict] = None,
        sesion: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.catalogo = catalogo or {}
        self.sesion = sesion or requests.Session()

    # ------------------------------------------------------------- cabeceras

    def _cabeceras(self) -> dict[str, str]:
        cabeceras = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"RadicadosPQRSF/{__version__}",
        }
        if self.token:
            cabeceras["Authorization"] = f"Bearer {self.token}"
        return cabeceras

    # -------------------------------------------------------------- catálogo

    def listar_areas(self) -> list[dict]:
        return self._get("/areas")

    def listar_tramites(self) -> list[dict]:
        return self._get("/tramites")

    def listar_usuarios(self) -> list[dict]:
        return self._get("/usuarios")

    def _get(self, ruta: str) -> list[dict]:
        respuesta = self.sesion.get(
            f"{self.base_url}{ruta}", headers=self._cabeceras(), timeout=self.timeout
        )
        respuesta.raise_for_status()
        return respuesta.json()

    # ------------------------------------------------------------- radicación

    def crear_radicado(
        self, correo: Correo, clasificacion: Clasificacion
    ) -> ResultadoRadicacion:
        tramite = self._resolver_tramite(clasificacion.tipo.value)
        if tramite is None:
            return ResultadoRadicacion(
                ok=False,
                error_codigo="SIN_MAPEO_TRAMITE",
                error_detalle=(
                    f"No hay tipo de trámite de DocxFlow para "
                    f"'{clasificacion.tipo.value}'. Revisar config/areas.yaml"
                ),
                reintentable=False,
            )

        destinatario = self._resolver_destinatario(clasificacion.area)
        if destinatario is None:
            return ResultadoRadicacion(
                ok=False,
                error_codigo="SIN_DESTINATARIO",
                error_detalle=(
                    f"No hay usuario destinatario para el área "
                    f"'{clasificacion.area}'. Revisar config/areas.yaml"
                ),
                reintentable=False,
            )

        cuerpo = self._construir_cuerpo(correo, clasificacion, tramite, destinatario)
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

    # ---------------------------------------------------------------- interno

    def _resolver_tramite(self, tipo_pqrsf: str) -> Optional[str]:
        return (self.catalogo.get("tramites") or {}).get(tipo_pqrsf)

    def _resolver_destinatario(self, area: str) -> Optional[str]:
        return (self.catalogo.get("destinatarios") or {}).get(area)

    def _interpretar(self, respuesta: requests.Response) -> ResultadoRadicacion:
        if respuesta.status_code in (200, 201):
            datos = respuesta.json()
            numero = datos.get("numero", "")

            valido, motivo = validar_numero_radicado(numero)
            if not valido:
                # El SGD devolvió algo que no cumple el contrato: no se puede
                # dar por radicado. Va al reporte para revisión humana.
                return ResultadoRadicacion(
                    ok=False,
                    error_codigo="NUMERO_INVALIDO",
                    error_detalle=motivo,
                    reintentable=False,
                )

            return ResultadoRadicacion(
                ok=True,
                radicado=Radicado(
                    numero=numero,
                    estado=datos.get("estado", "radicado"),
                    area_asignada=datos.get("destinatario", ""),
                    usuario_asignado=datos.get("destinatario", ""),
                ),
            )

        if respuesta.status_code == 409:
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
    def _construir_cuerpo(
        correo: Correo,
        clasificacion: Clasificacion,
        tramite: str,
        destinatario: str,
    ) -> dict:
        adjuntos = []
        for adjunto in correo.adjuntos:
            item = {
                "nombre": adjunto.nombre,
                "tipo_mime": adjunto.tipo_mime,
                "tamano_bytes": adjunto.tamano_bytes,
                "clasificacion": adjunto.clasificacion,
            }
            if adjunto.contenido:
                item["contenido_base64"] = base64.b64encode(
                    adjunto.contenido
                ).decode("ascii")
            adjuntos.append(item)

        return {
            "tipo_tramite": tramite,
            "tipo_pqrsf": clasificacion.tipo.value,
            "asunto": correo.asunto[:500],
            "remitente": {
                "email": correo.remitente_email,
                "nombre": correo.remitente_nombre,
            },
            "destinatario": {
                "email": destinatario,
                "nombre": correo.remitente_nombre,
                "area": clasificacion.area,
            },
            "cuerpo": correo.cuerpo,
            "recibido_en": correo.recibido_en.isoformat() if correo.recibido_en else None,
            "cantidad_documentos": len(adjuntos),
            "confianza": clasificacion.confianza,
            "adjuntos": adjuntos,
        }
