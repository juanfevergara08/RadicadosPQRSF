"""Comparación de nombres de archivo entre Gmail y DocxFlow.

DocxFlow no conserva el nombre original: le añade un sufijo numérico y
reemplaza tildes y espacios por guiones bajos.

    "Comprobante transacción.pdf"
      -> "Comprobante_transacci_n_980291.pdf"

Por eso no se puede comparar por igualdad. Se comparan los primeros
caracteres **normalizados** (sin tildes, sin símbolos, en minúsculas), que
sí se conservan.

Esto importa porque en el paso 3 hay varias filas en la tabla: si la
comparación falla, se clasificaría o se pondrían metadatos al documento
equivocado.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

LARGO_PREFIJO = 14


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y solo caracteres alfanuméricos."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return "".join(c for c in sin_tildes.lower() if c.isalnum())


def prefijo_de(nombre: str | Path, largo: int = LARGO_PREFIJO) -> str:
    """Primeros caracteres normalizados del nombre, sin extensión."""
    ruta = Path(str(nombre))
    return normalizar(ruta.stem)[:largo]


def coincide(nombre_original: str | Path, texto_fila: str, largo: int = LARGO_PREFIJO) -> bool:
    """¿El texto de la fila corresponde a ese archivo?"""
    prefijo = prefijo_de(nombre_original, largo)
    return bool(prefijo) and prefijo in normalizar(texto_fila)
