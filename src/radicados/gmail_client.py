"""Cliente de Gmail: leer correos y etiquetarlos.

Solo hace tres cosas, y ninguna toca DocxFlow:
  1. Listar los correos pendientes según `GMAIL_QUERY`.
  2. Convertir un mensaje de Gmail en un `Correo` normalizado.
  3. Poner/quitar etiquetas para marcar el avance.

La autenticación reutiliza el token que generó `scripts/verificar_gmail.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import Configuracion
from .correo_parser import (
    extraer_adjuntos,
    ids_de_adjuntos,
    leer_cabeceras,
    parsear_fecha,
    parsear_remitente,
)
from .models import Adjunto, Correo

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# 10 MB por adjunto: suficiente para facturas y documentos, y evita llenar RAM
MAX_BYTES_ADJUNTO = 10 * 1024 * 1024


class ErrorAutenticacion(RuntimeError):
    """Falta el archivo de credenciales o el token no es utilizable."""


class ClienteGmail:
    def __init__(
        self,
        config: Configuracion,
        servicio: Optional[object] = None,
    ) -> None:
        self.config = config
        self._servicio = servicio
        self._cache_etiquetas: dict[str, str] = {}

    # --------------------------------------------------------- autenticación

    @property
    def servicio(self):
        if self._servicio is None:
            self._servicio = self._autenticar()
        return self._servicio

    def _autenticar(self):
        ruta_credenciales = self.config.ruta(self.config.gmail_credentials_file)
        ruta_token = self.config.ruta(self.config.gmail_token_file)

        if not ruta_credenciales.exists():
            raise ErrorAutenticacion(
                f"No existe {ruta_credenciales}.\n"
                "Descarga el JSON de Google Cloud Console y guárdalo en esa ruta."
            )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        credenciales = None
        if ruta_token.exists():
            credenciales = Credentials.from_authorized_user_file(
                str(ruta_token), SCOPES
            )

        if not credenciales or not credenciales.valid:
            if credenciales and credenciales.expired and credenciales.refresh_token:
                credenciales.refresh(Request())
            else:
                flujo = InstalledAppFlow.from_client_secrets_file(
                    str(ruta_credenciales), SCOPES
                )
                credenciales = flujo.run_local_server(port=0)

            ruta_token.parent.mkdir(parents=True, exist_ok=True)
            ruta_token.write_text(credenciales.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=credenciales)

    # ------------------------------------------------------------ listado

    def listar_pendientes(self, limite: int = 10) -> list[str]:
        """IDs de mensajes que cumplen `GMAIL_QUERY`."""
        resultado = (
            self.servicio.users()
            .messages()
            .list(
                userId=self.config.gmail_mailbox,
                maxResults=limite,
                q=self.config.gmail_query,
            )
            .execute()
        )
        return [mensaje["id"] for mensaje in resultado.get("messages", [])]

    # ------------------------------------------------------------ lectura

    def obtener_correo(
        self,
        message_id_gmail: str,
        descargar_adjuntos: bool = True,
        clasificacion_anexo: str = "anexo",
    ) -> Correo:
        bruto = (
            self.servicio.users()
            .messages()
            .get(
                userId=self.config.gmail_mailbox,
                id=message_id_gmail,
                format="full",
            )
            .execute()
        )
        return self._convertir(bruto, descargar_adjuntos, clasificacion_anexo)

    def _convertir(
        self,
        bruto: dict,
        descargar_adjuntos: bool,
        clasificacion_anexo: str,
    ) -> Correo:
        payload = bruto.get("payload") or {}
        cabeceras = leer_cabeceras(payload)

        nombre, correo = parsear_remitente(cabeceras.get("from", ""))
        asunto = cabeceras.get("subject", "(sin asunto)")
        # Fallback al id interno de Gmail: todo correo necesita un identificador
        message_id = cabeceras.get("message-id") or f"<{bruto.get('id')}@gmail.internal>"

        adjuntos = extraer_adjuntos(payload, clasificacion_anexo)
        if descargar_adjuntos and adjuntos:
            adjuntos = self._descargar_adjuntos(
                bruto.get("id", ""), payload, adjuntos
            )

        from .correo_parser import extraer_cuerpo

        return Correo(
            message_id=message_id,
            thread_id=bruto.get("threadId", ""),
            remitente_email=correo,
            remitente_nombre=nombre,
            asunto=asunto,
            cuerpo=extraer_cuerpo(payload),
            recibido_en=parsear_fecha(cabeceras.get("date", "")),
            adjuntos=adjuntos,
        )

    def _descargar_adjuntos(
        self, gmail_id: str, payload: dict, adjuntos: list[Adjunto]
    ) -> list[Adjunto]:
        por_nombre = {adjunto.nombre: adjunto for adjunto in adjuntos}
        resultado: list[Adjunto] = []

        for nombre, attachment_id in ids_de_adjuntos(payload):
            adjunto = por_nombre.get(nombre)
            if adjunto is None:
                continue

            if adjunto.tamano_bytes > MAX_BYTES_ADJUNTO:
                # Se conserva el metadato pero sin contenido: queda en el reporte
                resultado.append(adjunto)
                continue

            respuesta = (
                self.servicio.users()
                .messages()
                .attachments()
                .get(
                    userId=self.config.gmail_mailbox,
                    messageId=gmail_id,
                    id=attachment_id,
                )
                .execute()
            )
            from .correo_parser import decodificar_b64url

            contenido = decodificar_b64url(respuesta.get("data", ""))
            resultado.append(
                Adjunto(
                    nombre=adjunto.nombre,
                    tipo_mime=adjunto.tipo_mime,
                    tamano_bytes=adjunto.tamano_bytes or len(contenido),
                    clasificacion=adjunto.clasificacion,
                    contenido=contenido,
                )
            )
        return resultado

    # ------------------------------------------------------------ etiquetas

    def id_etiqueta(self, nombre: str) -> str:
        """Devuelve el id de una etiqueta, creándola si no existe."""
        if nombre in self._cache_etiquetas:
            return self._cache_etiquetas[nombre]

        etiquetas = (
            self.servicio.users().labels().list(userId=self.config.gmail_mailbox).execute()
        )
        for etiqueta in etiquetas.get("labels", []):
            if etiqueta.get("name") == nombre:
                self._cache_etiquetas[nombre] = etiqueta["id"]
                return etiqueta["id"]

        creada = (
            self.servicio.users()
            .labels()
            .create(
                userId=self.config.gmail_mailbox,
                body={
                    "name": nombre,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        self._cache_etiquetas[nombre] = creada["id"]
        return creada["id"]

    def aplicar_etiqueta(self, message_id_gmail: str, nombre: str) -> None:
        self.servicio.users().messages().modify(
            userId=self.config.gmail_mailbox,
            id=message_id_gmail,
            body={"addLabelIds": [self.id_etiqueta(nombre)]},
        ).execute()

    def archivar(self, message_id_gmail: str) -> None:
        """Quita INBOX: el correo deja de estar en la bandeja."""
        self.servicio.users().messages().modify(
            userId=self.config.gmail_mailbox,
            id=message_id_gmail,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()
