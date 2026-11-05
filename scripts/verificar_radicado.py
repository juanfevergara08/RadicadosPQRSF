"""Verifica el estado guardado de un radicado (solo lectura)."""

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

JS = """() => {
    const val = (id) => { const e = document.getElementById(id); return e ? String(e.value||'') : ''; };
    const sel = (id) => { const e = document.getElementById(id);
        return e && e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : ''; };
    const filas = (sel_) => { const t = document.querySelector(sel_);
        if (!t) return [];
        return [...t.querySelectorAll('tr')].map(f =>
            [...f.querySelectorAll('td')].map(c => c.innerText.trim()).filter(Boolean)); };
    return {
        numero: val('ventanilla_radicacion_codigoRadicacion'),
        asunto: val('ventanilla_radicacion_asunto'),
        tramite: sel('ventanilla_radicacion_tramite'),
        envio: sel('ventanilla_radicacion_formaEnvioRespuesta'),
        unidad: sel('ventanilla_radicacion_unidadDistribucion'),
        clasificados: filas('#tbl_docs_clasificados')
    };
}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    args = parser.parse_args()
    if not args.confirmar:
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

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

        datos = marco.evaluate(JS)
        print(f"Número:   {datos['numero']}")
        print(f"Asunto:   {datos['asunto'][:70]!r}")
        print(f"Trámite:  {datos['tramite']!r}")
        print(f"Envío:    {datos['envio']!r}")
        print(f"Unidad:   {datos['unidad']!r}")
        print("\nDocumentos clasificados:")
        for fila in datos["clasificados"]:
            if fila and any("pdf" in c.lower() for c in fila):
                print("  |", " | ".join(fila)[:130])

        pag.screenshot(path=str(SALIDA / f"{marca}_verificacion_final.png"), full_page=True)
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
