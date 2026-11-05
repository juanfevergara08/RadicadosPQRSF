"""Cambia el tipo de trámite de un radicado existente.

    python scripts/cambiar_tramite.py --confirmar --radicado CCPE26-5223 --tramite 25

No despacha.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion
from radicados.docxflow_rpa import (
    abrir_contexto,
    esperar_frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"
CAMPO_TRAMITE = "#ventanilla_radicacion_tramite"
CAMPO_ENVIO = "#ventanilla_radicacion_formaEnvioRespuesta"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    parser.add_argument("--tramite", required=True, help="value del select, ej. 25")
    parser.add_argument("--envio", default="correo_electronico")
    args = parser.parse_args()
    if not args.confirmar:
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True, slow_mo=60)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")

        marco = esperar_frame_contenido(pag)
        marco.locator("#actviadorBusqueda").click()
        pag.wait_for_timeout(900)
        marco.locator("#rad").fill(args.radicado)
        marco.locator("#btn_buscar").click()
        pag.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pag)
        marco.locator("tr", has_text=args.radicado).first.get_by_role(
            "link", name="Registrar", exact=True
        ).first.click(timeout=20000)
        pag.wait_for_timeout(4000)
        marco = esperar_frame_contenido(pag)
        print(f"abierto: {marco.locator('#ventanilla_radicacion_codigoRadicacion').input_value()}")

        # paso 1 -> 4
        for _ in range(3):
            marco.locator("#link_next").click(timeout=15000)
            pag.wait_for_timeout(1800)
        print("en paso 4 (Trámite)")

        try:
            marco.locator(CAMPO_ENVIO).select_option(value=args.envio)
            print(f"forma de envío: {args.envio}")
        except Exception as error:  # noqa: BLE001
            print(f"[aviso] envío: {str(error).splitlines()[0][:80]}")

        marco.locator(CAMPO_TRAMITE).select_option(value=args.tramite)
        elegido = marco.locator(CAMPO_TRAMITE).evaluate(
            "el => el.options[el.selectedIndex].text"
        )
        print(f"trámite: {elegido!r} (value={args.tramite})")

        pag.screenshot(path=str(SALIDA / f"{marca}_tramite.png"), full_page=True)

        print("guardando borrador")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
        pag.wait_for_timeout(5000)

        aviso = marco.inner_text("body")
        for linea in aviso.splitlines():
            if "guard" in linea.lower() or "exitos" in linea.lower():
                print(f"aviso: {linea.strip()[:90]}")
                break

        pag.screenshot(path=str(SALIDA / f"{marca}_tramite_guardado.png"), full_page=True)
        print("NO se despachó")
        nav.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
