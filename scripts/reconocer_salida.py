"""Reconocimiento del módulo de salida de DocxFlow.

    python scripts/reconocer_salida.py --confirmar

Inicia sesión, lista los roles, cambia al rol de salida si existe y
volca los frames y enlaces visibles. No modifica nada.
"""

from __future__ import annotations

import argparse
import json
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

JS_ENLACES = """() => [...document.querySelectorAll('a, li, span, td')]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; })
    .map(el => ({ tag: el.tagName.toLowerCase(),
                  txt: (el.innerText||'').trim().slice(0,45),
                  href: (el.getAttribute('href')||'').slice(0,70) }))
    .filter(o => o.txt && o.txt.length > 3)"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not args.confirmar:
        print("Ejecuta con --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    SALIDA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=args.headless, slow_mo=60)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")
        print(f"login -> {pag.url}")

        roles = pag.locator("#opcRol option").all_inner_texts()
        print("\nROLES DISPONIBLES:")
        for i, r in enumerate(roles):
            print(f"  [{i}] {r}")

        salida = next((r for r in roles if "salida" in r.lower()), None)
        print(f"\nrol de salida: {salida!r}")

        if salida:
            pag.locator("#opcRol").select_option(label=salida)
            pag.locator("#frmRol").evaluate("(f) => f.submit()")
            pag.wait_for_load_state("networkidle", timeout=40000)
            pag.wait_for_timeout(4000)
            print(f"rol aplicado -> {pag.url}")

        print("\nFRAMES:")
        for i, f in enumerate(pag.frames):
            print(f"  [{i}] {f.url[:100]}")

        marco = esperar_frame_contenido(pag)
        print(f"\nframe contenido: {marco.url[:100]}")

        enlaces = marco.evaluate(JS_ENLACES)
        vistos = set()
        print("\nENLACES / TEXTOS VISIBLES (unicos):")
        for e in enlaces:
            clave = (e["txt"], e["href"])
            if clave in vistos:
                continue
            vistos.add(clave)
            print(f"  <{e['tag']}> {e['txt'][:42]:<42} {e['href'][:50]}")

        pag.screenshot(path=str(SALIDA / f"{marca}_salida_rol.png"), full_page=True)
        print(f"\ncaptura: {SALIDA / f'{marca}_salida_rol.png'}")
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
