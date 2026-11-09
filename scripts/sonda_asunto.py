"""Sonda: cómo guarda DocxFlow el asunto completo en la tabla de despachados."""

from __future__ import annotations

import argparse
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    args = parser.parse_args()
    if not args.confirmar:
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True, slow_mo=50)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")

        pag.locator("#opcRol").select_option(label="Rol de ventanilla única de salida")
        pag.locator("#frmRol").evaluate("(f) => f.submit()")
        pag.wait_for_load_state("networkidle", timeout=40000)
        pag.wait_for_timeout(4000)

        pag.get_by_text("Documentos de salida", exact=True).first.click(timeout=15000)
        pag.wait_for_timeout(2000)
        pag.get_by_text("Documentos despachados", exact=True).first.click(timeout=15000)
        pag.wait_for_timeout(5000)

        marco = esperar_frame_contenido(pag)
        html = marco.evaluate(
            """() => {
                const t = [...document.querySelectorAll('table')]
                    .sort((a,b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
                const tr = t.querySelectorAll('tbody tr')[0];
                const tds = [...tr.querySelectorAll('td')];
                return {
                    n: tds.length,
                    asunto_html: tds[7] ? tds[7].innerHTML : '',
                    asunto_texto: tds[7] ? tds[7].innerText : ''
                };
            }"""
        )
        print("celdas:", html["n"])
        print("\n--- ASUNTO TEXTO ---")
        print(html["asunto_texto"])
        print("\n--- ASUNTO HTML ---")
        print(html["asunto_html"][:1200])

        # Probar clic en "Ver más"
        enlace = marco.get_by_text("Ver más", exact=True).first
        if enlace.count():
            print("\n--- clic en 'Ver más' ---")
            enlace.click(timeout=5000)
            pag.wait_for_timeout(2500)
            despues = marco.evaluate(
                """() => {
                    const t = [...document.querySelectorAll('table')]
                        .sort((a,b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
                    const tds = [...t.querySelectorAll('tbody tr')[0].querySelectorAll('td')];
                    return { texto: tds[7] ? tds[7].innerText : '',
                             html: tds[7] ? tds[7].innerHTML.slice(0,400) : '' };
                }"""
            )
            print("texto:", despues["texto"][:300])
            print("html:", despues["html"][:300])
            pag.screenshot(path=str(SALIDA / "sonda_vermas.png"), full_page=True)
        else:
            print("\nno hay enlace 'Ver más'")

        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
