"""Paso 1 del RPA: reconocimiento de DocxFlow (versión 4).

    python scripts/reconocer_docxflow.py --confirmar

Usa la sesión robusta de `docxflow_rpa` y explora **dentro del frame** de la
aplicación, que es donde está la bandeja de radicación de entrada.

Recorre:
  1. Login y rol de ventanilla única de entrada
  2. Bandeja de radicación de entrada: inventario de botones y enlaces
  3. Intento de abrir el formulario de radicación
  4. Volcado de campos de cada pantalla (todos los frames)

No envía ningún formulario de radicación.
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
    ErrorLogin,
    abrir_contexto,
    frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"

JS_CAMPOS = """() => {
    const etiquetaDe = (el) => {
        if (el.id) {
            const l = document.querySelector(`label[for="${el.id}"]`);
            if (l) return l.innerText.trim();
        }
        const td = el.closest('td');
        if (td && td.previousElementSibling) {
            const t = td.previousElementSibling.innerText.trim();
            if (t && t.length < 70) return t.replace(/:$/, '');
        }
        if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
        if (el.title) return el.title;
        if (el.name) return el.name;
        return '';
    };
    return [...document.querySelectorAll('input, select, textarea, button')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
        .map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            etiqueta: etiquetaDe(el),
            opciones: el.tagName === 'SELECT'
                ? [...el.options].map(o => o.text.trim()).slice(0, 30) : []
        }));
}"""

JS_ACCIONES = """() => [...document.querySelectorAll(
        'button, a, input[type=button], input[type=submit], .boton, [onclick]')]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
    .map(el => ({
        tag: el.tagName.toLowerCase(),
        texto: (el.innerText || el.value || '').trim().slice(0, 50),
        id: el.id || '',
        onclick: (el.getAttribute('onclick') || '').slice(0, 100),
        href: (el.getAttribute('href') || '').slice(0, 100)
    }))
    .filter(a => a.texto || a.onclick || a.href)"""


def instantanea(pagina, marca: str, paso: str, resumen: dict) -> None:
    prefijo = SALIDA / f"{marca}_{paso}"
    try:
        pagina.screenshot(path=f"{prefijo}.png", full_page=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        Path(f"{prefijo}.html").write_text(pagina.content(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    frames_info = []
    for indice, frame in enumerate(pagina.frames):
        try:
            campos = frame.evaluate(JS_CAMPOS)
        except Exception:  # noqa: BLE001
            campos = []
        frames_info.append({"indice": indice, "url": frame.url, "campos": campos})
        # El formulario vive dentro del frame: hay que guardar su propio HTML
        if frame.url and "/login" not in frame.url and frame.url != "about:blank":
            try:
                Path(f"{prefijo}_f{indice}.html").write_text(
                    frame.content(), encoding="utf-8"
                )
            except Exception:  # noqa: BLE001
                pass

    resumen[paso] = {"url": pagina.url, "frames": frames_info}
    Path(f"{prefijo}_campos.json").write_text(
        json.dumps(frames_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n  >> {paso}  ({pagina.url[:70]})")
    for frame in frames_info:
        if not frame["campos"]:
            continue
        print(f"     frame {frame['indice']}: {frame['url'][:78]}")
        for campo in frame["campos"][:22]:
            etiqueta = campo["etiqueta"] or campo["name"] or campo["id"]
            extra = f" {campo['opciones'][:4]}" if campo["opciones"] else ""
            print(f"        <{campo['tag']}> {campo['id']!r:22} {etiqueta[:38]!r}{extra}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Inicia sesión en DocxFlow. No radica nada.")
        print("Ejecuta: python scripts/reconocer_docxflow.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_sesion = SALIDA / "sesion.json"
    resumen: dict = {}

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless)
        contexto = abrir_contexto(navegador, ruta_sesion)
        pagina = contexto.new_page()

        print("1. Autenticando")
        try:
            iniciar_sesion(pagina, config)
        except ErrorLogin as error:
            print(f"[FALLO] {error}")
            navegador.close()
            return 1
        guardar_sesion(contexto, ruta_sesion)
        print(f"   ok -> {pagina.url}")

        print("\n2. Asegurando rol de ventanilla única de entrada")
        try:
            if pagina.locator("#opcRol").count():
                pagina.locator("#opcRol").select_option(
                    label="Rol de ventanilla única de entrada"
                )
                pagina.locator("#frmRol").evaluate("(f) => f.submit()")
                pagina.wait_for_load_state("networkidle", timeout=40000)
                pagina.wait_for_timeout(2500)
                print("   rol aplicado")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error)[:100]}")

        pagina.wait_for_timeout(2000)
        instantanea(pagina, marca, "01_bandeja", resumen)

        contenido = frame_contenido(pagina)
        print(f"\n3. Inventario de acciones en el frame de contenido")
        try:
            acciones = contenido.evaluate(JS_ACCIONES)
            vistas = set()
            for accion in acciones:
                clave = accion["texto"] or accion["onclick"] or accion["href"]
                if not clave or clave in vistas:
                    continue
                vistas.add(clave)
                print(f"   [{accion['tag']}] {accion['texto'][:40]!r} "
                      f"id={accion['id'][:18]!r} onclick={accion['onclick'][:40]!r}")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error)[:100]}")

        print("\n4. Buscando el formulario de radicación")
        for etiqueta in ("Radicar", "Nuevo", "Registrar", "Adicionar", "Crear"):
            try:
                localizador = contenido.get_by_text(etiqueta, exact=False).first
                if localizador.count() and localizador.is_visible():
                    print(f"   clic en {etiqueta!r}")
                    localizador.click(timeout=8000)
                    pagina.wait_for_timeout(3500)
                    instantanea(pagina, marca, "02_formulario", resumen)
                    break
            except Exception as error:  # noqa: BLE001
                print(f"   [fallo] {etiqueta!r}: {str(error).splitlines()[0][:80]}")

        navegador.close()

    archivo = SALIDA / f"resumen_{marca}.json"
    archivo.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResumen: {archivo}")
    print("No se envió ningún formulario de radicación.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
