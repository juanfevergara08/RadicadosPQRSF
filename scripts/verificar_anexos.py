"""Verifica los documentos y anexos de un radicado (solo lectura).

    python scripts/verificar_anexos.py --confirmar --radicado CCPE26-7513

Abre el radicado, va al paso 3 y lista las tablas "Documentos Base" y
"Documentos clasificados". No escribe nada.
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

JS_TABLAS = """() => {
    const lee = (sel) => {
        const t = document.querySelector(sel);
        if (!t) return [];
        return [...t.querySelectorAll('tr')]
            .map(f => [...f.querySelectorAll('td,th')].map(c => (c.innerText || '').trim()))
            .filter(f => f.some(c => c));
    };
    return {
        base: lee('#tabla_documentos'),
        clasificados: lee('#tbl_docs_clasificados')
    };
}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", default="CCPE26-7513")
    argumentos = parser.parse_args()
    if not argumentos.confirmar:
        print("Ejecuta: python scripts/verificar_anexos.py --confirmar")
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

        marco.locator("#actviadorBusqueda").click()
        pagina.wait_for_timeout(900)
        marco.locator("#rad").fill(argumentos.radicado)
        marco.locator("#btn_buscar").click()
        pagina.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pagina)

        marco.locator("tr", has_text=argumentos.radicado).first.get_by_role(
            "link", name="Registrar", exact=True
        ).first.click(timeout=20000)
        pagina.wait_for_timeout(4000)
        marco = esperar_frame_contenido(pagina)
        print(f"abierto: {marco.locator('#ventanilla_radicacion_codigoRadicacion').input_value()}")

        # Paso 2 -> paso 3
        for _ in range(2):
            marco.locator("#link_next").click(timeout=15000)
            pagina.wait_for_timeout(2000)

        for _ in range(30):
            try:
                if not marco.get_by_text("Por favor espere", exact=False).first.is_visible():
                    break
            except Exception:  # noqa: BLE001
                break
            pagina.wait_for_timeout(1000)

        datos = marco.evaluate(JS_TABLAS)

        print("\n=== DOCUMENTOS BASE ===")
        for fila in datos["base"]:
            if any(fila):
                print("  |", " | ".join(f[:34] for f in fila))

        print("\n=== DOCUMENTOS CLASIFICADOS ===")
        for fila in datos["clasificados"]:
            if any(fila):
                print("  |", " | ".join(f[:34] for f in fila))

        print(f"\n  base: {len(datos['base'])} filas | "
              f"clasificados: {len(datos['clasificados'])} filas")

        pagina.screenshot(path=str(SALIDA / f"{marca}_verificacion_anexos.png"), full_page=True)
        print(f"  captura: {SALIDA / f'{marca}_verificacion_anexos.png'}")
        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
