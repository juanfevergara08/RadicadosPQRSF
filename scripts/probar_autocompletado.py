"""Sonda de los autocompletados de DocxFlow (solo lectura).

    python scripts/probar_autocompletado.py --confirmar --termino VERGARA

Consulta los mismos endpoints que usa el formulario para saber:
  - qué forma tiene la respuesta
  - qué término encuentra al funcionario destinatario
  - qué campos ocultos se llenan al elegir

No escribe nada en DocxFlow: son POST de búsqueda.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402
from radicados.docxflow_rpa import (  # noqa: E402
    ErrorLogin,
    abrir_contexto,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"

ENDPOINTS = {
    "funcionario (destinatario)": "/funcionario/autocomplete/1",
    "tercero (remitente)": "/recepcion/agenteexterno/autocompletado/1",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--termino", default="VERGARA")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Consulta los autocompletados. No radica nada.")
        print("Ejecuta: python scripts/probar_autocompletado.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        print("Autenticando...")
        try:
            iniciar_sesion(pagina, config)
        except ErrorLogin as error:
            print(f"[FALLO] {error}")
            navegador.close()
            return 1
        guardar_sesion(contexto, SALIDA / "sesion.json")
        print(f"ok -> {pagina.url}\n")

        for nombre, ruta in ENDPOINTS.items():
            print(f"=== {nombre}: POST {ruta} term={argumentos.termino!r}")
            try:
                respuesta = contexto.request.post(
                    f"{config.sgd_base_url}{ruta}",
                    form={"term": argumentos.termino},
                    timeout=30000,
                )
                print(f"    status: {respuesta.status}")
                texto = respuesta.text()
                try:
                    datos = respuesta.json()
                    print(f"    json: {json.dumps(datos, ensure_ascii=False)[:900]}")
                except Exception:  # noqa: BLE001
                    print(f"    texto: {texto[:400]}")
            except Exception as error:  # noqa: BLE001
                print(f"    [error] {error}")
            print()

        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
