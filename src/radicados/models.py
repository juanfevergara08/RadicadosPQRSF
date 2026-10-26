"""Modelos de datos del proceso de radicación.

Son independientes de Gmail y del SGD: cualquier origen (Gmail, IMAP, un CSV)
se convierte a `Correo`, y cualquier destino (SGD real, mock) consume
`Correo` + `Clasificacion`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TipoPQRSF(str, Enum):
    PETICION = "peticion"
    QUEJA = "queja"
    RECLAMO = "reclamo"
    SUGERENCIA = "sugerencia"
    FELICITACION = "felicitacion"
    DESCONOCIDO = "desconocido"


class EstadoProceso(str, Enum):
    """Ciclo de vida de un correo dentro del sistema."""

    PENDIENTE = "pendiente"  # registrado, aún sin procesar
    RADICADO = "radicado"  # tiene número de radicado en el SGD
    REVISION = "revision"  # confianza baja: espera decisión humana
    FALLIDO = "fallido"  # error técnico: va al reporte diario


@dataclass(frozen=True)
class Adjunto:
    nombre: str
    tipo_mime: str = "application/octet-stream"
    tamano_bytes: int = 0
    # Contenido en bytes. None cuando solo se listó el adjunto sin descargarlo.
    contenido: Optional[bytes] = None


@dataclass
class Correo:
    """Correo normalizado, listo para clasificar y radicar."""

    message_id: str
    remitente_email: str
    asunto: str
    cuerpo: str
    thread_id: str = ""
    remitente_nombre: str = ""
    recibido_en: Optional[datetime] = None
    adjuntos: list[Adjunto] = field(default_factory=list)

    def texto_para_clasificar(self) -> str:
        """Asunto + cuerpo, que es lo que realmente se analiza."""
        return f"{self.asunto}\n{self.cuerpo}"


@dataclass
class Clasificacion:
    tipo: TipoPQRSF
    area: str
    confianza: float  # 0.0 a 1.0
    motivo: str = ""
    origen: str = "regla"  # "regla" | "ia" | "defecto"

    @property
    def es_confiable(self) -> bool:
        return self.tipo is not TipoPQRSF.DESCONOCIDO


@dataclass
class Radicado:
    numero: str
    estado: str = "radicado"
    area_asignada: str = ""
    usuario_asignado: str = ""


@dataclass
class ResultadoRadicacion:
    ok: bool
    radicado: Optional[Radicado] = None
    error_codigo: str = ""
    error_detalle: str = ""
    reintentable: bool = False
