"""Estado persistente del proceso: la garantía de idempotencia.

Por qué existe este archivo
---------------------------
Si el proceso se cae después de crear un radicado pero antes de marcarlo como
hecho, la siguiente ejecución volvería a radicar el mismo correo. En un SGD
eso produce un radicado duplicado con número oficial, difícil de anular.

La defensa tiene dos capas:
  1. Aquí: `puede_radicar()` se niega si el Message-ID ya está en estado
     RADICADO. Es la comprobación local, instantánea.
  2. En el SGD: la cabecera `Idempotency-Key`. Aunque la capa 1 fallara, el
     SGD devuelve el radicado existente en vez de crear otro.

Se usa SQLite (librería estándar) para no agregar infraestructura.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import Correo, EstadoProceso

ESQUEMA = """
CREATE TABLE IF NOT EXISTS correos (
    message_id       TEXT PRIMARY KEY,
    thread_id        TEXT NOT NULL DEFAULT '',
    remitente        TEXT NOT NULL DEFAULT '',
    asunto           TEXT NOT NULL DEFAULT '',
    recibido_en      TEXT,
    estado           TEXT NOT NULL DEFAULT 'pendiente',
    tipo             TEXT NOT NULL DEFAULT '',
    area             TEXT NOT NULL DEFAULT '',
    confianza        REAL NOT NULL DEFAULT 0,
    numero_radicado  TEXT NOT NULL DEFAULT '',
    intentos         INTEGER NOT NULL DEFAULT 0,
    ultimo_error     TEXT NOT NULL DEFAULT '',
    motivo_revision  TEXT NOT NULL DEFAULT '',
    actualizado_en   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_correos_estado ON correos(estado);
CREATE INDEX IF NOT EXISTS idx_correos_radicado ON correos(numero_radicado);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AlmacenEstado:
    def __init__(self, ruta_db: str | Path) -> None:
        self.ruta = Path(ruta_db)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        conexion = sqlite3.connect(self.ruta)
        conexion.row_factory = sqlite3.Row
        try:
            yield conexion
            conexion.commit()
        finally:
            conexion.close()

    def _inicializar(self) -> None:
        with self._conexion() as conexion:
            conexion.executescript(ESQUEMA)

    # ---------------------------------------------------------------- lectura

    def obtener(self, message_id: str) -> Optional[dict]:
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM correos WHERE message_id = ?", (message_id,)
            ).fetchone()
        return dict(fila) if fila else None

    def puede_radicar(self, message_id: str) -> tuple[bool, str]:
        """Decide si este correo puede enviarse al SGD.

        Devuelve (permitido, motivo). Si ya está radicado, se bloquea.
        """
        fila = self.obtener(message_id)
        if fila is None:
            return True, "correo nuevo"
        if fila["estado"] == EstadoProceso.RADICADO.value:
            return False, f"ya radicado como {fila['numero_radicado']}"
        return True, f"reintento desde estado '{fila['estado']}'"

    def listar_por_estado(self, estado: EstadoProceso | str) -> list[dict]:
        valor = estado.value if isinstance(estado, EstadoProceso) else estado
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT * FROM correos WHERE estado = ? ORDER BY actualizado_en",
                (valor,),
            ).fetchall()
        return [dict(f) for f in filas]

    def resumen(self) -> dict[str, int]:
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT estado, COUNT(*) AS total FROM correos GROUP BY estado"
            ).fetchall()
        return {f["estado"]: f["total"] for f in filas}

    # --------------------------------------------------------------- escritura

    def registrar(self, correo: Correo) -> None:
        """Inserta el correo como PENDIENTE si no existe. No pisa nada."""
        with self._conexion() as conexion:
            conexion.execute(
                """
                INSERT INTO correos
                    (message_id, thread_id, remitente, asunto, recibido_en,
                     estado, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO NOTHING
                """,
                (
                    correo.message_id,
                    correo.thread_id,
                    correo.remitente_email,
                    correo.asunto,
                    correo.recibido_en.isoformat() if correo.recibido_en else None,
                    EstadoProceso.PENDIENTE.value,
                    _ahora(),
                ),
            )

    def marcar_radicado(
        self,
        message_id: str,
        numero_radicado: str,
        tipo: str,
        area: str,
        confianza: float,
    ) -> None:
        self._actualizar(
            message_id,
            estado=EstadoProceso.RADICADO.value,
            numero_radicado=numero_radicado,
            tipo=tipo,
            area=area,
            confianza=confianza,
            ultimo_error="",
        )

    def marcar_revision(
        self, message_id: str, tipo: str, area: str, confianza: float, motivo: str
    ) -> None:
        self._actualizar(
            message_id,
            estado=EstadoProceso.REVISION.value,
            tipo=tipo,
            area=area,
            confianza=confianza,
            motivo_revision=motivo,
        )

    def marcar_ignorado(self, message_id: str, motivo: str) -> None:
        self._actualizar(
            message_id,
            estado=EstadoProceso.IGNORADO.value,
            motivo_revision=motivo,
        )

    def marcar_fallido(self, message_id: str, codigo: str, detalle: str) -> None:
        with self._conexion() as conexion:
            conexion.execute(
                """
                UPDATE correos
                   SET estado = ?,
                       intentos = intentos + 1,
                       ultimo_error = ?,
                       actualizado_en = ?
                 WHERE message_id = ?
                """,
                (
                    EstadoProceso.FALLIDO.value,
                    f"{codigo}: {detalle}",
                    _ahora(),
                    message_id,
                ),
            )

    def _actualizar(self, message_id: str, **campos: object) -> None:
        if not campos:
            return
        campos["actualizado_en"] = _ahora()
        columnas = ", ".join(f"{nombre} = ?" for nombre in campos)
        valores = list(campos.values()) + [message_id]
        with self._conexion() as conexion:
            conexion.execute(
                f"UPDATE correos SET {columnas} WHERE message_id = ?", valores
            )
