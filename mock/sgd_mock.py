"""Mock del Sistema de Gestión Documental (DocxFlow).

Sirve para construir y probar todo el flujo mientras DocxFlow no documenta su
API. Implementa el contrato `contracts/radicacion.openapi.yaml`, incluyendo
la numeración real: CCPE<AA>-<NNNN> con `AA` = dos últimos dígitos del año y
consecutivo que reinicia cada año.

Uso:
    python mock/sgd_mock.py --puerto 8080
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

TRAMITES = [
    # Catálogo REAL de DocxFlow (verificado 2026-10-27 en el formulario).
    # `codigo` es el value numérico del <select> de trámite.
    {"codigo": "1", "nombre": "Correspondencia"},
    {"codigo": "25", "nombre": "Derechos de peticion"},
    {"codigo": "27", "nombre": "PQRSF-Peticiones"},
    {"codigo": "28", "nombre": "PQRSF-Queja"},
    {"codigo": "29", "nombre": "PQRSF-Reclamo"},
    {"codigo": "30", "nombre": "PQRSF-Sugerencias"},
    {"codigo": "31", "nombre": "PQRSF-Felicitaciones"},
    {"codigo": "37", "nombre": "Visita domiciliaria"},
    {"codigo": "38", "nombre": "FACTURAS JSP7"},
    {"codigo": "39", "nombre": "Facturas Gestion Humana"},
    {"codigo": "40", "nombre": "CONTRATOS JPS7"},
    {"codigo": "41", "nombre": "CONCILIACION BANCARIA"},
    {"codigo": "42", "nombre": "DocumentosSinRadicado"},
    {"codigo": "45", "nombre": "NUEVA AFILIACIÓN"},
    {"codigo": "46", "nombre": "CREDITOS TESORERIA"},
    {"codigo": "47", "nombre": "CajaMenor Jsp7"},
]

USUARIOS = [
    {"email": "jvergara@camarapereira.org.co", "nombre": "Julián Vergara", "area": "atencion_usuario"},
    {"email": "cartera@camarapereira.org.co", "nombre": "Cartera", "area": "financiera"},
]

CODIGOS_TRAMITE = {t["codigo"] for t in TRAMITES}

# Estado en memoria del mock
_radicados: dict[str, dict] = {}  # numero -> radicado
_por_idempotencia: dict[str, str] = {}  # Idempotency-Key -> numero
_consecutivo = 0
_anio_consecutivo: int | None = None
_candado = threading.Lock()


class HandlerSGD(BaseHTTPRequestHandler):
    server_version = "SgdMock/0.2"
    # HTTP/1.1 + Content-Length permite keep-alive real. Con HTTP/1.0 el
    # servidor cierra la conexión tras cada respuesta y el cliente que
    # reutiliza el socket falla de forma intermitente.
    protocol_version = "HTTP/1.1"

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
        if self.path == "/tramites":
            self._responder(200, TRAMITES)
            return
        if self.path.startswith("/usuarios"):
            self._responder(200, USUARIOS)
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
        self._error(404, "NO_ENCONTRADO", f"Ruta desconocida: {self.path}")

    # --------------------------------------------------------------- lógica

    def _crear_radicado(self) -> None:
        global _consecutivo, _anio_consecutivo

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

        tramite = cuerpo.get("tipo_tramite", "")
        if tramite not in CODIGOS_TRAMITE:
            self._error(422, "TIPO_TRAMITE_INEXISTENTE", f"Trámite no existe: {tramite!r}")
            return

        remitente = cuerpo.get("remitente") or {}
        if not remitente.get("email"):
            self._error(422, "SIN_REMITENTE", "Falta remitente.email")
            return

        destinatario = cuerpo.get("destinatario") or {}
        if not destinatario.get("email"):
            self._error(422, "SIN_DESTINATARIO", "Falta destinatario.email")
            return

        adjuntos = cuerpo.get("adjuntos") or []
        cantidad = cuerpo.get("cantidad_documentos")
        if cantidad is None or int(cantidad) != len(adjuntos):
            self._error(
                422,
                "CANTIDAD_DOCUMENTOS_INCONSISTENTE",
                f"cantidad_documentos={cantidad} pero hay {len(adjuntos)} adjuntos",
            )
            return

        for adjunto in adjuntos:
            if not adjunto.get("clasificacion"):
                self._error(
                    422,
                    "ADJUNTO_SIN_CLASIFICAR",
                    f"El adjunto {adjunto.get('nombre')!r} no tiene clasificación",
                )
                return

        with _candado:
            anio = datetime.now(timezone.utc).year
            if _anio_consecutivo != anio:
                _anio_consecutivo = anio
                _consecutivo = 0
            _consecutivo += 1

            numero = f"CCPE{anio % 100:02d}-{_consecutivo:04d}"
            radicado = {
                "numero": numero,
                "estado": "radicado",
                "tipo_tramite": tramite,
                "destinatario": destinatario.get("email", ""),
                "creado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "idempotency_key": clave,
                "asunto": cuerpo.get("asunto", ""),
            }
            _radicados[numero] = radicado
            _por_idempotencia[clave] = numero

        self._responder(201, radicado)


class ServidorSGD(ThreadingHTTPServer):
    """Servidor del mock.

    `handle_error` silencia los cortes de conexión: cuando el cliente cierra
    el socket (o se detiene el servidor) el handler lanza WinError 10053 y su
    traza ensucia la salida de las pruebas sin ser un fallo real.
    """

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys

        excepcion = sys.exc_info()[1]
        if isinstance(
            excepcion, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
        ):
            return
        super().handle_error(request, client_address)


def crear_servidor(puerto: int = 8080) -> ThreadingHTTPServer:
    servidor = ServidorSGD(("127.0.0.1", puerto), HandlerSGD)
    servidor.daemon_threads = True
    return servidor


def reiniciar_estado() -> None:
    global _consecutivo, _anio_consecutivo
    with _candado:
        _radicados.clear()
        _por_idempotencia.clear()
        _consecutivo = 0
        _anio_consecutivo = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock del SGD para RadicadosPQRSF")
    parser.add_argument("--puerto", type=int, default=8080)
    argumentos = parser.parse_args()

    servidor = crear_servidor(argumentos.puerto)
    print(f"Mock del SGD escuchando en http://127.0.0.1:{argumentos.puerto}")
    print("Endpoints: /areas /tramites /usuarios | POST /radicados")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
