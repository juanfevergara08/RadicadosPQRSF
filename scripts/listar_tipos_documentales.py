"""Lista las opciones del catálogo de tipo documental que coincidan."""

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
from radicados.nombres import normalizar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    parser.add_argument("--buscar", nargs="*", default=["devolu", "cedu", "certific", "banc"])
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
        for _ in range(2):
            marco.locator("#link_next").click(timeout=15000)
            pag.wait_for_timeout(2000)

        objetivo = normalizar("rg_ft_038_formato_devolucion")[:12]
        for i in range(marco.locator("#tabla_documentos tr").count()):
            fila = marco.locator("#tabla_documentos tr").nth(i)
            if objetivo in normalizar(fila.inner_text()):
                fila.get_by_text("Clasificar", exact=False).first.click(timeout=20000)
                break
        pag.wait_for_timeout(3000)

        opciones = marco.evaluate(
            """() => {
                const s = document.querySelector('#selectTipoDocumental');
                return s ? [...s.options].map(o => o.text.trim()) : [];
            }"""
        )
        print(f"total opciones: {len(opciones)}")
        for texto in opciones:
            bajo = texto.lower()
            if any(b.lower() in bajo for b in args.buscar):
                print("  *", texto)

        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
