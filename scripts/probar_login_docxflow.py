"""Prueba aislada del login de DocxFlow.

    python scripts/probar_login_docxflow.py --confirmar

Solo inicia sesión y reporta en qué estado quedó. No navega ni radica nada.
Sirve para separar problemas de autenticación de problemas de recorrido de
la interfaz.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Inicia sesión en DocxFlow con las credenciales del .env.")
        print("Ejecuta: python scripts/probar_login_docxflow.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta_sesion = SALIDA / "sesion.json"

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless)
        contexto = abrir_contexto(navegador, ruta_sesion)
        pagina = contexto.new_page()

        print(f"Usuario: {config.docxflow_user}")
        print(f"URL:     {config.sgd_base_url}")

        try:
            iniciar_sesion(pagina, config)
        except ErrorLogin as error:
            print(f"\n[FALLO] {error}")
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            pagina.screenshot(path=str(SALIDA / f"login_fallido_{marca}.png"))
            print(f"Captura: {SALIDA / f'login_fallido_{marca}.png'}")
            navegador.close()
            return 1

        guardar_sesion(contexto, ruta_sesion)

        print("\n[OK] Sesión iniciada.")
        print(f"     URL: {pagina.url}")
        print(f"     frames: {len(pagina.frames)}")
        for indice, frame in enumerate(pagina.frames):
            print(f"       [{indice}] {frame.url[:90]}")

        try:
            print(f"\nRoles: {pagina.locator('#opcRol option').all_inner_texts()}")
            print(f"Rol actual: {pagina.locator('#opcRol').input_value()}")
        except Exception:  # noqa: BLE001
            print("\nNo hay selector de rol (puede que ya esté elegido).")

        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        pagina.screenshot(path=str(SALIDA / f"login_ok_{marca}.png"), full_page=True)
        print(f"\nCaptura: {SALIDA / f'login_ok_{marca}.png'}")
        print(f"Sesión guardada en: {ruta_sesion}")

        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
