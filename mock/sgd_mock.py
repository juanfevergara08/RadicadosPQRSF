"""Mock del Sistema de Gestión Documental.

Sirve para construir y probar todo el flujo mientras el SGD real no está
definido. Implementa el contrato `contracts/radicacion.openapi.yaml`.

Uso:
    python mock/sgd_mock.py --puerto 8080

Importante: el mock SÍ implementa la idempotencia (devuelve 200 con el
radicado existente si repites el Idempotency-Key). Si el SGD real no la
implementa, ese es el punto que hay que negociar con el proveedor.
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AREAS = [
    {"codigo": "atencion_usuario", "nombre": "Atención al Usuario"},
    {"codigo": "financiera", "nombre": "Financiera y Cartera"},
    {"codigo": "tecnica", "nombre": "Técnica y Operaciones"},
    {"codigo": "juridica", "nombre": "Jurídica"},
    {"codigo": "talento_humano", "nombre": "Talento Humano"},
]

TIPOS_VALIDOS = {"peticion", "queja", "reclamo", "sugerencia", "felicitacion"}
CODIGOS_AREA = {area["codigo"] for area in AREAS}

# Estado en memoria del mock
_radicados: dict[str, dict] = {}  # numero -> radicado
_por_idempotencia: dict[str, str] = {}  # Idempotency-Key -> numero
_consecutivo = 0
_candado = threading.Lock()


class HandlerSGD(BaseHTTPRequestHandler):
    server_version = "SgdMock/0.1"

    # Silenciar el log de cada request para no ensuciar la salida del demo
    def log_message(self, formato: str, *args: object) -> None:  # noqa: A003
        return

    # ------------------------------------------------------------------ utils

    def _responder(self, codigo: int, cuerpo: dict | list) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _error(self, codigo: int, nombre: str, mensaje: str) -> None:
        self._responder(codigo, {"codigo": nombre, "mensaje": mensaje})

    def _leer_cuerpo(self) -> dict:
        largo = int(self.headers.get("Content-Length", "0"))
        if not largo:
            return {}
        crudo = self.rfile.read(largo)
        try:
            return json.loads(crudo.decode("utf-8"))
        except ValueError:
            return {}

    # -------------------------------------------------------------------- GET

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/areas":
            self._responder(200, AREAS)
            return

        if self.path == "/_debug/radicados":
            self._responder(200, list(_radicados.values()))
            return

        if self.path.startswith("/radicados/"):
            numero = self.path.split("/radicados/", 1)[1]
            radicado = _radicados.get(numero)
            if radicado is None:
                self._error(404, "NO_ENCONTRADO", f"No existe {numero}")
                return
            self._responder(200, radicado)
            return

        self._error(404, "NO_ENCONTRADO", f"Ruta desconocida: {self.path}")

    # -------------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/radicados":
            self._crear_radicado()
            return

        if self.path.startswith("/radicados/") and self.path.endswith("/asignacion"):
            numero = self.path[len("/radicados/") : -len("/asignacion")]
            self._asignar(numero)
            return

        self._error(404, "NO_ENCONTRADO", f"Ruta desconocida: {self.path}")

    # --------------------------------------------------------------- lógica

    def _crear_radicado(self) -> None:
        global _consecutivo

        clave = self.headers.get("Idempotency-Key", "").strip()
        if not clave:
            self._error(422, "SIN_IDEMPOTENCY_KEY", "Falta la cabecera Idempotency-Key")
            return

        with _candado:
            if clave in _por_idempotencia:
                numero = _por_idempotencia[clave]
                self._responder(200, _radicados[numero])
                return

        cuerpo = self._leer_cuerpo()

        tipo = cuerpo.get("tipo", "")
        if tipo not in TIPOS_VALIDOS:
            self._error(422, "TIPO_INVALIDO", f"Tipo no permitido: {tipo!r}")
            return

        remitente = cuerpo.get("remitente") or {}
        if not remitente.get("email"):
            self._error(422, "SIN_REMITENTE", "El correo debe traer remitente.email")
            return

        area = cuerpo.get("area_sugerida", "")
        if area and area not in CODIGOS_AREA:
            self._error(422, "AREA_INEXISTENTE", f"Área no existe: {area!r}")
            return

        with _candado:
            _consecutivo += 1
            anio = datetime.now(timezone.utc).year
            numero = f"PQRSF-{anio}-{_consecutivo:06d}"
            radicado = {
                "numero": numero,
                "estado": "radicado",
                "tipo": tipo,
                "area_sugerida": area,
                "area_asignada": "",
                "usuario_asignado": "",
                "creado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "idempotency_key": clave,
                "asunto": cuerpo.get("asunto", ""),
            }
            _radicados[numero] = radicado
            _por_idempotencia[clave] = numero

        self._responder(201, radicado)

    def _asignar(self, numero: str) -> None:
        radicado = _radicados.get(numero)
        if radicado is None:
            self._error(404, "NO_ENCONTRADO", f"No existe {numero}")
            return
        if radicado.get("area_asignada"):
            self._error(409, "YA_ASIGNADO", f"{numero} ya fue asignado")
            return

        cuerpo = self._leer_cuerpo()
        area = cuerpo.get("area", "")
        if area and area not in CODIGOS_AREA:
            self._error(422, "AREA_INEXISTENTE", f"Área no existe: {area!r}")
            return

        radicado["area_asignada"] = area
        radicado["usuario_asignado"] = cuerpo.get("usuario", "")
        radicado["estado"] = "asignado"
        self._responder(200, radicado)


def crear_servidor(puerto: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", puerto), HandlerSGD)


def reiniciar_estado() -> None:
    """Vacía el estado en memoria (útil para pruebas)."""
    global _consecutivo
    with _candado:
        _radicados.clear()
        _por_idempotencia.clear()
        _consecutivo = 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock del SGD para RadicadosPQRSF")
    parser.add_argument("--puerto", type=int, default=8080)
    argumentos = parser.parse_args()

    servidor = crear_servidor(argumentos.puerto)
    print(f"Mock del SGD escuchando en http://127.0.0.1:{argumentos.puerto}")
    print("Endpoints: GET /areas | POST /radicados | GET /radicados/{numero}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
