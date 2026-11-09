"""Busca y abre 'Documentos despachados' del módulo de salida."""

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

JS_ENLACES = """() => [...document.querySelectorAll('a')]
    .map(a => ({ txt: (a.innerText||'').trim().slice(0,50),
                 href: (a.getAttribute('href')||'').slice(0,90) }))
    .filter(o => o.txt || o.href)"""


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
        nav = p.chromium.launch(headless=args.headless, slow_mo=60)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")

        pag.locator("#opcRol").select_option(label="Rol de ventanilla única de salida")
        pag.locator("#frmRol").evaluate("(f) => f.submit()")
        pag.wait_for_load_state("networkidle", timeout=40000)
        pag.wait_for_timeout(4000)
        print(f"rol salida aplicado -> {pag.url}")

        print("\n=== ENLACES DEL SHELL ===")
        for f in pag.frames:
            if f == pag.main_frame:
                for e in f.evaluate(JS_ENLACES):
                    if any(k in (e["txt"] + e["href"]).lower()
                           for k in ("salida", "despach", "documento")):
                        print(f"  {e['txt'][:45]:<45} {e['href'][:60]}")

        print("\n=== FRAMES ===")
        for i, f in enumerate(pag.frames):
            print(f"  [{i}] {f.url[:100]}")

        pag.screenshot(path=str(SALIDA / f"{marca}_menu_salida.png"), full_page=True)
        print(f"\ncaptura: {SALIDA / f'{marca}_menu_salida.png'}")
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
