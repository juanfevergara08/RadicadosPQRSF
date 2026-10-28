"""Verifica que un radicado ya no esté pendiente en la bandeja de entrada.

    python scripts/verificar_despacho.py --confirmar --radicado CCPE26-7513

Solo lectura: entra a Documentos de entrada, busca el número y reporta si
sigue listado como pendiente.
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
    abrir_contexto,
    esperar_frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", default="CCPE26-7513")
    argumentos = parser.parse_args()
    if not argumentos.confirmar:
        print("Ejecuta: python scripts/verificar_despacho.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True, slow_mo=60)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        iniciar_sesion(pagina, config)
        guardar_sesion(contexto, SALIDA / "sesion.json")
        marco = esperar_frame_contenido(pagina)

        if marco.locator("#actviadorBusqueda").count():
            marco.locator("#actviadorBusqueda").click()
            pagina.wait_for_timeout(900)
        marco.locator("#rad").fill(argumentos.radicado)
        marco.locator("#btn_buscar").click()
        pagina.wait_for_timeout(4500)
        marco = esperar_frame_contenido(pagina)

        texto = marco.inner_text("body")
        aparece = argumentos.radicado in texto

        print(f"Buscando {argumentos.radicado} en Documentos de entrada")
        if aparece:
            print("  RESULTADO: AÚN aparece en la bandeja (sigue pendiente)")
            for linea in texto.splitlines():
                if argumentos.radicado in linea:
                    print(f"    {linea.strip()[:120]}")
        else:
            print("  RESULTADO: ya NO aparece como pendiente -> despachado")

        filas = marco.locator("table tr").count()
        print(f"  filas visibles en la tabla: {filas}")

        pagina.screenshot(
            path=str(SALIDA / f"{marca}_verificar_despacho.png"), full_page=True
        )
        print(f"  captura: {SALIDA / f'{marca}_verificar_despacho.png'}")
        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
