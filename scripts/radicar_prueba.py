"""Radicación real en DocxFlow por RPA (fase 3).

    # 1) Llenar el formulario SIN generar nada (seguro, es el paso 2 del plan)
    python scripts/radicar_prueba.py --confirmar --llenar-solo

    # 2) Generar el radicado, deteniéndose ANTES de Despachar
    python scripts/radicar_prueba.py --confirmar --generar

Qué hace:
  - Inicia sesión y asegura el rol de ventanilla única de entrada
  - Abre el formulario de radicación de entrada
  - Pulsa "Nuevo radicado" para empezar en blanco
  - Llena remitente, destinatario, asunto, trámite y "Envío directo *"
  - Con --generar, pulsa "Generar radicado"
  - NUNCA pulsa "Despachar": solo lo detecta y lo reporta

El freno es deliberado: un radicado generado ya tiene número oficial.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import cargar_catalogo_areas, Configuracion  # noqa: E402
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

CAMPO_REMITENTE = "#ventanilla_radicacion_remitente_tercero"
CAMPO_DESTINATARIO = "#ventanilla_radicacion_destinatario"
CAMPO_ASUNTO = "#ventanilla_radicacion_asunto"
CAMPO_TRAMITE = "#ventanilla_radicacion_tramite"
CAMPO_UNIDAD = "#ventanilla_radicacion_unidadDistribucion"
CAMPO_RADICADO = "#ventanilla_radicacion_codigoRadicacion"

MENU_AUTOCOMPLETE = "ul.ui-autocomplete:visible li"


def captura(pagina, marca: str, paso: str) -> Path:
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / f"{marca}_{paso}.png"
    try:
        pagina.screenshot(path=str(ruta), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    return ruta


def elegir_autocompletado(
    marco, selector: str, termino: str, objetivo: str | None, etiqueta: str
) -> bool:
    """Escribe en un campo con autocompletado y elige una sugerencia.

    Escribir el texto no basta: el formulario guarda el id del registro
    elegido, así que hay que hacer clic en la sugerencia.
    """
    print(f"   {etiqueta}: buscando {termino!r}")
    marco.locator(selector).click()
    marco.locator(selector).fill("")
    marco.locator(selector).type(termino, delay=90)

    try:
        marco.wait_for_selector(MENU_AUTOCOMPLETE, timeout=15000)
    except Exception:  # noqa: BLE001
        print(f"      [fallo] no aparecieron sugerencias para {termino!r}")
        return False

    opciones = marco.locator(MENU_AUTOCOMPLETE)
    textos = [opciones.nth(i).inner_text().strip() for i in range(opciones.count())]
    print(f"      sugerencias: {textos[:6]}")

    indice = 0
    if objetivo:
        for posicion, texto in enumerate(textos):
            if objetivo.lower() in texto.lower():
                indice = posicion
                break
        else:
            print(f"      [aviso] ninguna sugerencia contiene {objetivo!r}; se usa la primera")

    opciones.nth(indice).click()
    marco.wait_for_timeout(800)
    return True


def abrir_formulario(pagina, marco) -> None:
    """Llega al formulario de radicación de entrada."""
    print("   abriendo 'Documentos de entrada'")
    try:
        pagina.get_by_text("Documentos de entrada", exact=False).first.click(timeout=8000)
        pagina.wait_for_timeout(2000)
    except Exception:  # noqa: BLE001
        print("      [aviso] no se encontró la pestaña; se continúa")

    # Entrar por la bandeja es la vía que funcionó en el reconocimiento
    print("   entrando por la bandeja (clic en Registrar)")
    marco = frame_contenido(pagina)
    marco.get_by_text("Registrar", exact=False).first.click(timeout=15000)
    pagina.wait_for_timeout(3500)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument(
        "--llenar-solo",
        action="store_true",
        help="llena el formulario y no genera nada (recomendado la primera vez)",
    )
    parser.add_argument(
        "--generar",
        action="store_true",
        help="pulsa Generar radicado; nunca pulsa Despachar",
    )
    parser.add_argument("--remitente", default="PRUEBAS", help="término a buscar como remitente")
    parser.add_argument("--asunto", default="PRUEBAS RADICADOS")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Este script escribe en DocxFlow (formulario de radicación).")
        print("Ejecuta:  python scripts/radicar_prueba.py --confirmar --llenar-solo")
        return 2

    if not (argumentos.llenar_solo or argumentos.generar):
        print("Elige un modo: --llenar-solo (seguro) o --generar (crea el radicado)")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    catalogo = cargar_catalogo_areas(config.ruta(config.areas_config_file))
    tramite = str((catalogo.get("tramites") or {}).get("peticion", "32"))
    destinatario = (catalogo.get("destinatarios") or {}).get(
        "atencion_usuario", "JUAN FELIPE VERGARA OSORIO"
    )

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 80)
    print("RADICACIÓN DE PRUEBA")
    print(f"  trámite ....... {tramite} (Solicitud de información)")
    print(f"  destinatario .. {destinatario}")
    print(f"  asunto ........ {argumentos.asunto}")
    print(f"  remitente ..... buscar {argumentos.remitente!r}")
    print(f"  modo .......... {'GENERAR' if argumentos.generar else 'SOLO LLENAR'}")
    print("=" * 80)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless, slow_mo=120)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        print("\n1. Autenticando")
        try:
            iniciar_sesion(pagina, config)
        except ErrorLogin as error:
            print(f"[FALLO] {error}")
            navegador.close()
            return 1
        guardar_sesion(contexto, SALIDA / "sesion.json")
        print(f"   ok -> {pagina.url}")

        print("\n2. Rol de ventanilla única de entrada")
        try:
            if pagina.locator("#opcRol").count():
                pagina.locator("#opcRol").select_option(
                    label="Rol de ventanilla única de entrada"
                )
                pagina.locator("#frmRol").evaluate("(f) => f.submit()")
                pagina.wait_for_load_state("networkidle", timeout=40000)
                pagina.wait_for_timeout(2500)
            print("   ok")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error)[:90]}")

        print("\n3. Abriendo formulario")
        abrir_formulario(pagina, frame_contenido(pagina))
        marco = frame_contenido(pagina)
        captura(pagina, marca, "01_formulario_abierto")
        print(f"   frame: {marco.url[:80]}")

        print("\n4. Nuevo radicado en blanco")
        try:
            marco.locator("#nuevo-radicado").click(timeout=10000)
            pagina.wait_for_timeout(3000)
            marco = frame_contenido(pagina)
            numero = marco.locator(CAMPO_RADICADO).input_value()
            print(f"   número actual: {numero!r}")
            captura(pagina, marca, "02_nuevo_radicado")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error)[:110]}")

        print("\n5. Llenando el formulario")

        ok_remitente = elegir_autocompletado(
            marco, CAMPO_REMITENTE, argumentos.remitente, None, "Remitente"
        )
        if not ok_remitente:
            print("   [FALLO] sin remitente no se puede continuar")
            captura(pagina, marca, "03_error_remitente")
            navegador.close()
            return 1

        elegir_autocompletado(
            marco, CAMPO_DESTINATARIO, destinatario, destinatario, "Destinatario"
        )

        marco.locator(CAMPO_ASUNTO).fill(argumentos.asunto)
        print(f"   Asunto: {argumentos.asunto!r}")

        marco.locator(CAMPO_TRAMITE).select_option(value=tramite)
        print(f"   Trámite: {tramite}")

        # "Envío directo *" es el valor -1 dentro del select de unidad
        marco.locator(CAMPO_UNIDAD).select_option(value="-1")
        print("   Distribución: Envío directo * (-1)")

        pagina.wait_for_timeout(1500)
        captura(pagina, marca, "03_lleno")
        print("\n   Formulario lleno. Captura guardada.")

        if argumentos.generar:
            print("\n6. Pulsando 'Generar radicado'")
            try:
                marco.locator("#generar-radicado").click(timeout=15000)
                pagina.wait_for_timeout(5000)
                marco = frame_contenido(pagina)
                numero = marco.locator(CAMPO_RADICADO).input_value()
                print(f"   Número de radicación: {numero!r}")
                captura(pagina, marca, "04_generado")
            except Exception as error:  # noqa: BLE001
                print(f"   [FALLO] {str(error)[:150]}")
                captura(pagina, marca, "04_error_generar")
                navegador.close()
                return 1
        else:
            print("\n6. Modo solo llenar: no se generó nada.")

        print("\n7. Comprobando que NO se despachó")
        try:
            despachar = marco.get_by_text("Despachar", exact=False)
            if despachar.count():
                print("   existe un botón 'Despachar' — NO se ha pulsado")
            else:
                print("   no aparece 'Despachar' todavía")
        except Exception:  # noqa: BLE001
            print("   no se pudo comprobar")

        captura(pagina, marca, "05_final")
        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    print("Revisa en DocxFlow antes de continuar. No se despachó nada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
