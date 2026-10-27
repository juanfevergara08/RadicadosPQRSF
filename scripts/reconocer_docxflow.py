"""Paso 1 del RPA: reconocer la pantalla de DocxFlow (NO radica nada).

    pip install playwright
    playwright install chromium

    python scripts/reconocer_docxflow.py --confirmar

Qué hace:
  1. Abre un navegador visible.
  2. Inicia sesión con DOCXFLOW_USER / DOCXFLOW_PASSWORD del .env.
  3. Guarda captura de pantalla + HTML de la página.
  4. Lista todos los campos del formulario con sus etiquetas.

No envía ningún formulario de radicación. Solo inicia sesión y observa.

Sirve para obtener los selectores reales antes de escribir la automatización.
Si la página cambia, se vuelve a correr y se actualizan los datos.
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"


def volcar_campos(pagina) -> list[dict]:
    """Lista los campos visibles del formulario con su etiqueta."""
    return pagina.evaluate(
        """() => {
            const etiquetaDe = (el) => {
                if (el.id) {
                    const l = document.querySelector(`label[for="${el.id}"]`);
                    if (l) return l.innerText.trim();
                }
                const padre = el.closest('label');
                if (padre) return padre.innerText.trim();
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                if (el.placeholder) return el.placeholder;
                if (el.name) return el.name;
                return '';
            };
            const visibles = [...document.querySelectorAll('input, select, textarea, button, a[href]')]
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                });
            return visibles.map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                placeholder: el.placeholder || '',
                etiqueta: etiquetaDe(el),
                texto: (el.innerText || el.value || '').trim().slice(0, 60),
                href: el.getAttribute('href') || ''
            }));
        }"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconocimiento de DocxFlow")
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="necesario para ejecutar: confirma que autorizas iniciar sesión",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="sin ventana visible (por defecto se muestra para que veas qué pasa)",
    )
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Este script inicia sesión en DocxFlow con tus credenciales.")
        print("No radica nada, pero deja registro de acceso.")
        print("\nSi estás de acuerdo, ejecuta:")
        print("    python scripts/reconocer_docxflow.py --confirmar")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] Falta Playwright. Instala con:")
        print("    pip install playwright")
        print("    playwright install chromium")
        return 1

    config = Configuracion.cargar()
    if not config.docxflow_user or not config.docxflow_password:
        print("[ERROR] Faltan DOCXFLOW_USER y DOCXFLOW_PASSWORD en el archivo .env")
        return 1

    SALIDA.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless)
        contexto = navegador.new_context(viewport={"width": 1400, "height": 900})
        pagina = contexto.new_page()

        print(f"Abriendo {config.sgd_base_url} ...")
        pagina.goto(config.sgd_base_url, wait_until="networkidle", timeout=60000)

        print(f"URL: {pagina.url}")
        print(f"Título: {pagina.title()}")

        # Intento heurístico de inicio de sesión
        usuario = pagina.locator(
            'input[type="email"], input[name*="user" i], input[id*="user" i], '
            'input[name*="usuario" i], input[id*="usuario" i], input[type="text"]'
        ).first
        clave = pagina.locator('input[type="password"]').first

        if usuario.count() and clave.count():
            print("Formulario de login detectado. Iniciando sesión...")
            usuario.fill(config.docxflow_user)
            clave.fill(config.docxflow_password)
            clave.press("Enter")
            pagina.wait_for_load_state("networkidle", timeout=60000)
            print(f"Sesión iniciada. URL: {pagina.url}")
        else:
            print("[AVISO] No se detectó formulario de login en esta página.")
            print("        Revisa la captura para ver qué se cargó.")

        pagina.wait_for_timeout(2500)

        captura = SALIDA / f"docxflow_{marca}.png"
        pagina.screenshot(path=str(captura), full_page=True)

        html = SALIDA / f"docxflow_{marca}.html"
        html.write_text(pagina.content(), encoding="utf-8")

        campos = volcar_campos(pagina)
        campos_json = SALIDA / f"campos_{marca}.json"
        campos_json.write_text(
            json.dumps(campos, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(f"\nCaptura:  {captura}")
        print(f"HTML:     {html}")
        print(f"Campos:   {campos_json}")
        print(f"\nSe encontraron {len(campos)} elementos interactivos:\n")
        for campo in campos[:40]:
            etiqueta = campo["etiqueta"] or campo["texto"] or campo["name"] or campo["id"]
            print(f"  <{campo['tag']}{' type=' + campo['type'] if campo['type'] else ''}> "
                  f"id={campo['id']!r:22} etiqueta={etiqueta[:44]!r}")

        navegador.close()

    print("\nReconocimiento terminado. No se envió ningún formulario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
