"""Diagnóstico de frames de DocxFlow.

    python scripts/diagnostico_frames.py --confirmar

Muestra qué frames existen en cada momento (antes y después de elegir rol).
Útil cuando el script no encuentra la bandeja. No radica nada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402
from radicados.docxflow_rpa import abrir_contexto, guardar_sesion, iniciar_sesion  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"


def listar(pagina, etiqueta: str) -> None:
    print(f"\n--- {etiqueta} ---")
    print(f"pagina: {pagina.url}")
    for indice, frame in enumerate(pagina.frames):
        print(f"  [{indice}] {frame.url[:100]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    argumentos = parser.parse_args()
    if not argumentos.confirmar:
        print("Ejecuta: python scripts/diagnostico_frames.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        iniciar_sesion(pagina, config)
        guardar_sesion(contexto, SALIDA / "sesion.json")
        listar(pagina, "después del login")

        print("\nGuardando captura del estado post-login")
        pagina.screenshot(path=str(SALIDA / "frames_post_login.png"), full_page=True)

        if pagina.locator("#opcRol").count():
            print("\nEligiendo rol de ventanilla única de entrada")
            pagina.locator("#opcRol").select_option(
                label="Rol de ventanilla única de entrada"
            )
            pagina.locator("#frmRol").evaluate("(f) => f.submit()")
            pagina.wait_for_load_state("networkidle", timeout=40000)
            pagina.wait_for_timeout(4000)
            listar(pagina, "después de elegir rol")
            pagina.screenshot(path=str(SALIDA / "frames_post_rol.png"), full_page=True)

        print("\nEsperando 12s observando cambios de frames")
        for segundo in range(1, 13):
            pagina.wait_for_timeout(1000)
            urls = " | ".join((f.url.split("/")[-2] if f.url.count("/") > 2 else f.url[:20]) for f in pagina.frames)
            print(f"  t={segundo:2}s  pagina={pagina.url.split('/')[-1]:<12} frames={urls[:110]}")

        listar(pagina, "estado final")
        pagina.screenshot(path=str(SALIDA / "frames_final.png"), full_page=True)
        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
