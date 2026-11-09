"""Abre el submenú de 'Documentos de salida' y lista sus opciones."""

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
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"

JS_MENU = """() => [...document.querySelectorAll(
        '.dhtmlxMebu_Item, .sub_item_text, .menu_item, [class*=sub_item]')]
    .map(e => (e.innerText||'').trim())
    .filter(t => t && t.length > 2 && t.length < 60)"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not args.confirmar:
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=args.headless, slow_mo=70)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")

        pag.locator("#opcRol").select_option(label="Rol de ventanilla única de salida")
        pag.locator("#frmRol").evaluate("(f) => f.submit()")
        pag.wait_for_load_state("networkidle", timeout=40000)
        pag.wait_for_timeout(4000)

        print("clic en 'Documentos de salida'")
        pag.get_by_text("Documentos de salida", exact=True).first.click(timeout=15000)
        pag.wait_for_timeout(2500)

        print("\n=== TEXTOS DEL MENU DESPLEGADO ===")
        vistos = set()
        for t in pag.evaluate(JS_MENU):
            if t not in vistos:
                vistos.add(t)
                print(f"  - {t}")

        print("\n=== ENLACES VISIBLES CON href ===")
        for a in pag.evaluate("""() => [...document.querySelectorAll('a')]
                .filter(a => { const r = a.getBoundingClientRect(); return r.width>0 && r.height>0; })
                .map(a => ({ t: (a.innerText||'').trim().slice(0,45),
                             h: (a.getAttribute('href')||'').slice(0,80) }))"""):
            if a["t"] or a["h"]:
                print(f"  {a['t'][:40]:<40} {a['h'][:55]}")

        pag.screenshot(path=str(SALIDA / f"{marca}_submenu_salida.png"), full_page=True)
        print(f"\ncaptura: {SALIDA / f'{marca}_submenu_salida.png'}")
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
