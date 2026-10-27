"""Clasificación de correos: tipo PQRSF + área destino + confianza.

Estrategia en dos niveles
-------------------------
1. **Reglas** (este módulo): busca palabras clave del catálogo `config/areas.yaml`.
   Es determinista, gratis y auditable. Cubre la mayoría de los correos, porque
   el remitente casi siempre escribe "solicito", "reclamo", "felicito"...

2. **IA** (`ClasificadorIA`): solo entra cuando las reglas no alcanzan el umbral.
   Es lo que resuelve tu problema real: "no todos usan estas palabras".

La confianza no es un adorno: decide la ruta. Bajo el umbral el correo NO se
radica, va a revisión humana. Eso evita radicados basura, que son peores que
un correo sin radicar porque hay que anularlos a mano en el SGD.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Protocol

from .models import Clasificacion, Correo, TipoPQRSF


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para que 'Petición' == 'peticion'."""
    texto = texto.lower()
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes)


def _contar_coincidencias(texto_normalizado: str, palabras: list[str]) -> int:
    """Cuenta cuántas palabras clave del catálogo aparecen en el texto."""
    total = 0
    for palabra in palabras:
        if normalizar(palabra) in texto_normalizado:
            total += 1
    return total


def _confianza_por_coincidencias(coincidencias: int) -> float:
    if coincidencias >= 3:
        return 0.9
    if coincidencias == 2:
        return 0.75
    if coincidencias == 1:
        return 0.5
    return 0.0


def esta_excluido(correo: Correo, exclusiones: dict | None) -> str:
    """Devuelve el motivo si el correo NO es una PQRSF, o '' si sí lo es.

    Las notificaciones automáticas suelen contener palabras como "solicitud"
    o "factura" y el clasificador las puntúa alto. Filtrarlas antes evita
    radicados basura en el SGD.
    """
    if not exclusiones:
        return ""

    remitente = normalizar(correo.remitente_email)
    asunto = normalizar(correo.asunto)

    for patron in exclusiones.get("remitentes") or []:
        if normalizar(patron) in remitente:
            return f"remitente excluido: {patron}"

    for patron in exclusiones.get("asuntos") or []:
        if normalizar(patron) in asunto:
            return f"asunto excluido: {patron}"

    return ""


class ClasificadorIA(Protocol):
    """Contrato del clasificador por IA. Se implementa en la fase 2."""

    def clasificar(self, correo: Correo) -> Optional[Clasificacion]:
        ...


class ClasificadorReglas:
    def __init__(self, catalogo: dict, area_por_defecto: str = "atencion_usuario") -> None:
        self.tipos: dict[str, dict] = catalogo.get("tipos", {}) or {}
        self.areas: dict[str, dict] = catalogo.get("areas", {}) or {}
        self.area_por_defecto = catalogo.get("area_por_defecto", area_por_defecto)

    def clasificar(self, correo: Correo) -> Clasificacion:
        texto = normalizar(correo.texto_para_clasificar())

        tipo, coincidencias_tipo = self._mejor_tipo(texto)
        area, coincidencias_area = self._mejor_area(texto)

        confianza_tipo = _confianza_por_coincidencias(coincidencias_tipo)
        confianza_area = _confianza_por_coincidencias(coincidencias_area)

        # El tipo pesa más que el área: radicar con el tipo correcto y el área
        # equivocada es recuperable; lo contrario no.
        confianza = round(0.65 * confianza_tipo + 0.35 * confianza_area, 3)

        motivo = (
            f"tipo={tipo.value} ({coincidencias_tipo} coincidencias), "
            f"area={area} ({coincidencias_area} coincidencias)"
        )

        return Clasificacion(
            tipo=tipo,
            area=area,
            confianza=confianza,
            motivo=motivo,
            origen="regla",
        )

    def _mejor_tipo(self, texto: str) -> tuple[TipoPQRSF, int]:
        mejor = TipoPQRSF.DESCONOCIDO
        mejores_coincidencias = 0
        for clave, definicion in self.tipos.items():
            coincidencias = _contar_coincidencias(texto, definicion.get("palabras", []))
            if coincidencias > mejores_coincidencias:
                mejores_coincidencias = coincidencias
                try:
                    mejor = TipoPQRSF(clave)
                except ValueError:
                    continue
        return mejor, mejores_coincidencias

    def _mejor_area(self, texto: str) -> tuple[str, int]:
        mejor_area = self.area_por_defecto
        mejores_coincidencias = 0
        for clave, definicion in self.areas.items():
            coincidencias = _contar_coincidencias(texto, definicion.get("palabras", []))
            if coincidencias > mejores_coincidencias:
                mejores_coincidencias = coincidencias
                mejor_area = clave
        return mejor_area, mejores_coincidencias


class ClasificadorHibrido:
    """Reglas primero; IA solo si la regla no alcanza el umbral."""

    def __init__(
        self,
        reglas: ClasificadorReglas,
        umbral: float,
        ia: Optional[ClasificadorIA] = None,
    ) -> None:
        self.reglas = reglas
        self.umbral = umbral
        self.ia = ia

    def clasificar(self, correo: Correo) -> Clasificacion:
        base = self.reglas.clasificar(correo)

        if base.confianza >= self.umbral or self.ia is None:
            return base

        # Las reglas no alcanzaron: se intenta con IA.
        try:
            propuesta = self.ia.clasificar(correo)
        except Exception as error:  # la IA no debe tumbar el proceso
            base.motivo += f" | IA falló: {error}"
            return base

        if propuesta is None:
            base.motivo += " | IA no disponible"
            return base

        # Se combina: si ambas fuentes coinciden en tipo, sube la confianza.
        if propuesta.tipo == base.tipo and base.tipo is not TipoPQRSF.DESCONOCIDO:
            propuesta.confianza = min(1.0, max(propuesta.confianza, base.confianza) + 0.15)
            propuesta.origen = "regla+ia"
        propuesta.motivo = f"{propuesta.motivo} | reglas: {base.motivo}"
        return propuesta
