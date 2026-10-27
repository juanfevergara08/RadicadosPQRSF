"""Recorre el wizard de radicación de DocxFlow y reporta cada paso.

    python scripts/inspeccionar_formulario.py --confirmar

Avanza con #link_next ("Siguiente") y, en cada paso, lista los campos
visibles con su etiqueta, si son obligatorios y las opciones de los selects.

No escribe ni envía nada: no genera radicado.
"""

from __future__ import annotations

import argparse
import json
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

JS_PASO_VISIBLE = """() => {
    const pasos = [...document.querySelectorAll('div.step')]
        .filter(d => getComputedStyle(d).display !== 'none');
    return pasos.map(d => d.id);
}"""

JS_CAMPOS = """() => {
    const etiqueta = (el) => {
        if (el.id) {
            const l = document.querySelector(`label[for="${el.id}"]`);
            if (l) return l.innerText.trim().replace(/\\s+/g, ' ');
        }
        const td = el.closest('td');
        if (td && td.previousElementSibling) {
            const t = td.previousElementSibling.innerText.trim().replace(/\\s+/g, ' ');
            if (t.length < 70) return t.replace(/:$/, '');
        }
        return el.name || el.id || '';
    };
    return [...document.querySelectorAll('input, select, textarea')]
        .filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && el.type !== 'hidden';
        })
        .map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.type,
            id: el.id,
            name: el.name,
            etiqueta: etiqueta(el),
            obligatorio: el.required || (el.className || '').includes('required') || false,
            valor: String(el.value || '').slice(0, 40),
            opciones: el.tagName === 'SELECT'
                ? [...el.options].map(o => `${o.value}=${o.text.trim()}`).slice(0, 20)
                : []
        }));
}"""


def volcar(pagina, marco, etiqueta: str, datos: dict) -> None:
    pasos = marco.evaluate(JS_PASO_VISIBLE)
    campos = marco.evaluate(JS_CAMPOS)
    print(f"\n--- {etiqueta}  |  pasos visibles: {pasos}  |  {len(campos)} campos ---")
    for campo in campos:
        oblig = " *" if campo["obligatorio"] else ""
        print(f"  <{campo['tag']}>{campo['type'] or '':<9} id={campo['id'][:42]:<42}{oblig}")
        print(f"      etiqueta: {campo['etiqueta'][:70]}")
        if campo["opciones"]:
            print(f"      opciones: {campo['opciones'][:8]}")
    datos[etiqueta] = {"pasos": pasos, "campos": campos}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    argumentos = parser.parse_args()
    if not argumentos.confirmar:
        print("Ejecuta: python scripts/inspeccionar_formulario.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    datos: dict = {}

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        iniciar_sesion(pagina, config)
        guardar_sesion(contexto, SALIDA / "sesion.json")
        print(f"login -> {pagina.url}")

        if pagina.locator("#opcRol").count():
            pagina.locator("#opcRol").select_option(
                label="Rol de ventanilla única de entrada"
            )
            pagina.locator("#frmRol").evaluate("(f) => f.submit()")
            pagina.wait_for_load_state("networkidle", timeout=40000)
            pagina.wait_for_timeout(4000)

        marco = esperar_frame_contenido(pagina)
        marco.get_by_role("link", name="Registrar", exact=True).first.click(timeout=20000)
        pagina.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pagina)

        marco.locator("#nuevo-radicado").click(timeout=12000)
        pagina.wait_for_timeout(2500)
        marco = esperar_frame_contenido(pagina)
        print(f"formulario en blanco -> {marco.url[:90]}")

        for numero in range(1, 6):
            volcar(pagina, marco, f"step{numero}", datos)
            pagina.screenshot(
                path=str(SALIDA / f"{marca}_step{numero}.png"), full_page=True
            )
            try:
                Path(SALIDA / f"{marca}_step{numero}.html").write_text(
                    marco.content(), encoding="utf-8"
                )
            except Exception:  # noqa: BLE001
                pass
            if numero < 5:
                try:
                    marco.locator("#link_next").click(timeout=10000)
                    pagina.wait_for_timeout(1800)
                except Exception as error:  # noqa: BLE001
                    print(f"\n  [aviso] no se pudo avanzar: {str(error)[:100]}")
                    break

        ruta = SALIDA / f"{marca}_wizard.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGuardado: {ruta}")
        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
