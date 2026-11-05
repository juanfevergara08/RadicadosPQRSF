"""Sonda: abre el diálogo de clasificación y lista sus controles."""

from __future__ import annotations

import argparse
import json
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

JS = """() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
    return {
        selects: [...document.querySelectorAll('select')].filter(vis).map(s => ({
            id: s.id, name: s.name, cls: s.className,
            opciones: [...s.options].slice(0,5).map(o => o.text.trim())
        })),
        botones: [...document.querySelectorAll('button, input[type=button]')].filter(vis)
            .map(b => ({ id: b.id, txt: (b.innerText||b.value||'').trim().slice(0,25) })),
        dialogos: [...document.querySelectorAll('[role=dialog], .ui-dialog, [class*=dialog], [id*=dialog]')]
            .filter(vis).map(d => ({ id: d.id, cls: d.className.slice(0,60) }))
    };
}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    args = parser.parse_args()
    if not args.confirmar:
        print("Ejecuta con --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
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

        for _ in range(2):
            marco.locator("#link_next").click(timeout=15000)
            pag.wait_for_timeout(2000)

        # abrir el "Clasificar" de la fila pendiente (rg_ft)
        objetivo = normalizar("rg_ft_038_formato_devolucion")[:12]
        abierto = False
        for fila in [marco.locator("#tabla_documentos tr").nth(i)
                     for i in range(marco.locator("#tabla_documentos tr").count())]:
            try:
                if objetivo in normalizar(fila.inner_text()):
                    fila.get_by_text("Clasificar", exact=False).first.click(timeout=20000)
                    abierto = True
                    break
            except Exception:  # noqa: BLE001
                continue
        print("clic en fila:", abierto)
        pag.wait_for_timeout(3000)

        datos = marco.evaluate(JS)
        print(json.dumps(datos, ensure_ascii=False, indent=2))
        pag.screenshot(path=str(SALIDA / "sonda_dialogo.png"), full_page=True)
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
