"""Sonda del remitente: por qué no queda asignado remitenteId.

    python scripts/probar_remitente.py --confirmar

Abre el radicado, va al paso 2 y prueba tres formas de elegir el remitente,
reportando remitenteId después de cada una. No guarda ni despacha.
"""

from __future__ import annotations

import argparse
import sys
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
CAMPO = "#ventanilla_radicacion_remitente_tercero"
MENU = "ul.ui-autocomplete:visible li"

JS_ESTADO = """() => ({
    tipoRemitenteId: typeof remitenteId,
    remitenteId: typeof remitenteId === 'undefined' ? null : remitenteId,
    remitenteTipo: typeof remitenteTipo === 'undefined' ? null : remitenteTipo,
    agenteId: typeof agenteId === 'undefined' ? null : agenteId,
    texto: (document.getElementById('ventanilla_radicacion_remitente_tercero') || {}).value || '',
    infoVisible: (() => {
        const el = document.getElementById('remitente_info');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { width: r.width, height: r.height, texto: (el.innerText || '').slice(0, 120) };
    })()
})"""


def estado(marco, etiqueta: str) -> None:
    datos = marco.evaluate(JS_ESTADO)
    print(f"   [{etiqueta}] remitenteId={datos['remitenteId']} "
          f"(tipo={datos['tipoRemitenteId']}) remitenteTipo={datos['remitenteTipo']}")
    print(f"      texto={datos['texto'][:60]!r}")
    print(f"      info={datos['infoVisible']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", default="CCPE26-7513")
    parser.add_argument("--remitente", default="LUZ ENITH OSORIO OROZCO")
    argumentos = parser.parse_args()
    if not argumentos.confirmar:
        print("Ejecuta: python scripts/probar_remitente.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True, slow_mo=80)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        iniciar_sesion(pagina, config)
        guardar_sesion(contexto, SALIDA / "sesion.json")

        marco = esperar_frame_contenido(pagina)
        marco.locator("#actviadorBusqueda").click()
        pagina.wait_for_timeout(800)
        marco.locator("#rad").fill(argumentos.radicado)
        marco.locator("#btn_buscar").click()
        pagina.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pagina)

        marco.locator("tr", has_text=argumentos.radicado).first.get_by_role(
            "link", name="Registrar", exact=True
        ).first.click(timeout=15000)
        pagina.wait_for_timeout(4000)
        marco = esperar_frame_contenido(pagina)

        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2000)
        estado(marco, "inicial en paso 2")

        campo = marco.locator(CAMPO)
        campo.click()
        campo.fill("")
        campo.type(argumentos.remitente, delay=90)
        marco.wait_for_selector(MENU, timeout=20000)

        opciones = marco.locator(MENU)
        textos = [opciones.nth(i).inner_text().strip() for i in range(opciones.count())]
        print(f"\n   sugerencias ({opciones.count()}):")
        for i, t in enumerate(textos[:5]):
            print(f"      [{i}] {t[:90]}")

        print("\n   A) teclado: ArrowDown + Enter")
        campo.press("ArrowDown")
        marco.wait_for_timeout(300)
        campo.press("Enter")
        marco.wait_for_timeout(1800)
        estado(marco, "A teclado")

        print("\n   B) clic en el primer li")
        campo.click()
        campo.fill("")
        campo.type(argumentos.remitente, delay=90)
        marco.wait_for_selector(MENU, timeout=20000)
        marco.locator(MENU).first.click()
        marco.wait_for_timeout(1800)
        estado(marco, "B clic li")

        print("\n   C) clic en el <a> dentro del li")
        campo.click()
        campo.fill("")
        campo.type(argumentos.remitente, delay=90)
        marco.wait_for_selector(MENU, timeout=20000)
        marco.locator(MENU + " a").first.click()
        marco.wait_for_timeout(1800)
        estado(marco, "C clic a")

        pagina.screenshot(path=str(SALIDA / "sonda_remitente.png"), full_page=True)
        navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
