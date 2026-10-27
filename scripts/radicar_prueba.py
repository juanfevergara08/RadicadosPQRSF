"""Radicación real en DocxFlow por RPA (fase 3).

    python scripts/radicar_prueba.py --confirmar --generar

ORDEN REAL DEL SISTEMA (verificado):
    1. Nuevo radicado -> paso 1 con 4 campos
    2. "Generar radicado"  -> asigna CCPE<AA>-<NNNN> y REVELA los controles
                              del wizard (#controles_radicacion)
    3. Siguiente -> paso 2: remitente, destinatario, asunto
    4. Siguiente -> paso 3: documentos y anexos
    5. Siguiente -> paso 4: forma de envío de respuesta, trámite
    6. Siguiente -> paso 5: unidad de distribución (Envío directo = -1)

El número se consume en el paso 2, no al final. Por eso el script pide
--generar explícitamente.

NUNCA pulsa "Despachar".
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
    esperar_frame_contenido,
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
CAMPO_REFERENCIA = "#ventanilla_radicacion_referencia"
CAMPO_FOLIOS = "#ventanilla_radicacion_campoAnexos"
CAMPO_ENVIO_RESP = "#ventanilla_radicacion_formaEnvioRespuesta"
CAMPO_TRANSPORTE = "#ventanilla_radicacion_tipoTransporteInterno"

MENU_AUTOCOMPLETE = "ul.ui-autocomplete:visible li"


def captura(pagina, marca: str, paso: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def siguiente(pagina, marco, destino: str) -> None:
    marco.locator("#link_next").click(timeout=15000)
    pagina.wait_for_timeout(2000)
    print(f"   -> {destino}")


def elegir_autocompletado(
    marco, selector: str, termino: str, objetivo: str | None, etiqueta: str
) -> bool:
    print(f"   {etiqueta}: buscando {termino!r}")
    marco.locator(selector).wait_for(state="visible", timeout=20000)

    campo = marco.locator(selector)
    campo.click()
    campo.fill("")
    campo.type(termino, delay=90)

    try:
        marco.wait_for_selector(MENU_AUTOCOMPLETE, timeout=20000)
    except Exception:  # noqa: BLE001
        print(f"      [FALLO] sin sugerencias para {termino!r}")
        return False

    opciones = marco.locator(MENU_AUTOCOMPLETE)
    textos = [opciones.nth(i).inner_text().strip() for i in range(opciones.count())]
    print(f"      sugerencias: {textos[:5]}")

    indice = 0
    if objetivo:
        for posicion, texto in enumerate(textos):
            if objetivo.lower() in texto.lower():
                indice = posicion
                break

    opciones.nth(indice).click()
    marco.wait_for_timeout(1200)
    print(f"      elegido: {textos[indice][:70]}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument(
        "--generar",
        action="store_true",
        help="genera el radicado (consume un número real) y luego llena el resto",
    )
    parser.add_argument("--solo-paso1", action="store_true", help="llena solo el paso 1")
    parser.add_argument("--remitente", default="LUZ ENITH OSORIO OROZCO")
    parser.add_argument("--asunto", default="PRUEBAS RADICADOS")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Este script escribe en DocxFlow.")
        print("Ejecuta:  python scripts/radicar_prueba.py --confirmar --generar")
        return 2
    if not (argumentos.generar or argumentos.solo_paso1):
        print("Indica --generar (radicado real) o --solo-paso1 (sin generar)")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    catalogo = cargar_catalogo_areas(config.ruta(config.areas_config_file))
    tramite = str((catalogo.get("tramites") or {}).get("peticion", "32"))
    destinatario = (catalogo.get("destinatarios") or {}).get(
        "atencion_usuario", "JUAN FELIPE VERGARA OSORIO"
    )
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 84)
    print("RADICACIÓN DE PRUEBA — DocxFlow")
    print(f"  trámite ....... {tramite} Solicitud de información")
    print(f"  remitente ..... {argumentos.remitente}")
    print(f"  destinatario .. {destinatario}")
    print(f"  asunto ........ {argumentos.asunto}")
    print(f"  distribución .. Envío directo (-1)")
    print(f"  modo .......... {'GENERAR (real)' if argumentos.generar else 'SOLO PASO 1'}")
    print("=" * 84)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless, slow_mo=90)
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

        print("\n2. Rol")
        try:
            if pagina.locator("#opcRol").count():
                actual = pagina.locator("#opcRol").evaluate(
                    "el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''"
                )
                if "ventanilla" not in (actual or "").lower():
                    pagina.locator("#opcRol").select_option(
                        label="Rol de ventanilla única de entrada"
                    )
                    pagina.locator("#frmRol").evaluate("(f) => f.submit()")
                    pagina.wait_for_load_state("networkidle", timeout=40000)
                    pagina.wait_for_timeout(4000)
                    print("   rol cambiado")
                else:
                    print(f"   ya activo: {actual}")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error).splitlines()[0][:90]}")

        print("\n3. Radicación de entrada")
        marco = esperar_frame_contenido(pagina)
        marco.get_by_role("link", name="Registrar", exact=True).first.click(timeout=20000)
        pagina.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pagina)

        print("\n4. Nuevo radicado en blanco")
        marco.locator("#nuevo-radicado").click(timeout=15000)
        pagina.wait_for_timeout(2500)
        marco = esperar_frame_contenido(pagina)
        print(f"   url: {marco.url[:80]}")

        print("\n5. Paso 1 — datos de radicación")
        marco.locator(CAMPO_REFERENCIA).fill(argumentos.asunto)
        marco.locator(CAMPO_FOLIOS).fill("1")
        print(f"   referencia: {argumentos.asunto!r} | folios y anexos: 1")
        captura(pagina, marca, "01_paso1")

        if not argumentos.generar:
            print("\n   Modo solo paso 1: no se generó nada.")
            captura(pagina, marca, "02_fin")
            navegador.close()
            return 0

        print("\n6. GENERANDO EL RADICADO (consume número real)")
        marco.locator("#generar-radicado").click(timeout=25000)
        pagina.wait_for_timeout(6000)
        marco = esperar_frame_contenido(pagina)
        numero = marco.locator(CAMPO_RADICADO).input_value()
        if not numero:
            print("   [FALLO] el número quedó vacío: la generación no ocurrió")
            captura(pagina, marca, "error_generar")
            navegador.close()
            return 1
        print(f"   NÚMERO DE RADICACIÓN: {numero}")
        captura(pagina, marca, "02_generado")

        print("\n7. Paso 2 — Información de correspondencia")
        siguiente(pagina, marco, "paso 2")

        if not elegir_autocompletado(
            marco, CAMPO_REMITENTE, argumentos.remitente, None, "Remitente"
        ):
            print("   [FALLO] sin remitente el radicado queda incompleto")
            captura(pagina, marca, "error_remitente")
            navegador.close()
            return 1

        elegir_autocompletado(
            marco, CAMPO_DESTINATARIO, destinatario, destinatario, "Destinatario"
        )

        marco.locator(CAMPO_ASUNTO).wait_for(state="visible", timeout=15000)
        marco.locator(CAMPO_ASUNTO).fill(argumentos.asunto)
        # jQuery Validate escucha change/blur, no solo el evento input que
        # dispara fill(). Sin esto el asunto queda escrito pero marcado como
        # vacío ("Digite un asunto").
        marco.locator(CAMPO_ASUNTO).dispatch_event("change")
        marco.locator(CAMPO_ASUNTO).blur()
        pagina.wait_for_timeout(800)
        print(f"   asunto: {argumentos.asunto!r}")
        captura(pagina, marca, "03_correspondencia")

        print("\n8. Paso 3 — Documento y anexos (sin adjuntos)")
        siguiente(pagina, marco, "paso 3")
        captura(pagina, marca, "04_anexos")

        print("\n9. Paso 4 — Envío de respuesta y trámite")
        siguiente(pagina, marco, "paso 4")
        try:
            marco.locator(CAMPO_ENVIO_RESP).select_option(value="correo_electronico")
            print("   forma de envío: correo_electronico")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] forma de envío: {str(error).splitlines()[0][:80]}")
        marco.locator(CAMPO_TRAMITE).select_option(value=tramite)
        print(f"   trámite: {tramite}")
        captura(pagina, marca, "05_tramite")

        print("\n10. Paso 5 — Distribución (Envío directo)")
        siguiente(pagina, marco, "paso 5")
        try:
            marco.locator(CAMPO_UNIDAD).select_option(value="-1")
            print("   unidad: Envío directo * (-1)")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] unidad: {str(error).splitlines()[0][:80]}")
        try:
            marco.locator(CAMPO_TRANSPORTE).select_option(value="1")
            print("   tipo de transporte: Digital (1)")
        except Exception:  # noqa: BLE001
            pass
        captura(pagina, marca, "06_distribucion")

        print("\n11. Comprobando 'Despachar' (NO se pulsa)")
        try:
            if marco.get_by_text("Despachar", exact=False).count():
                print("   existe 'Despachar' — NO se ha pulsado")
            else:
                print("   'Despachar' no visible en este paso")
        except Exception:  # noqa: BLE001
            print("   no se pudo comprobar")

        captura(pagina, marca, "07_final")
        navegador.close()

    print("\n" + "=" * 84)
    print(f"Radicado generado: {numero}")
    print(f"Capturas en {SALIDA}")
    print("NO se despachó. Revísalo en DocxFlow antes de continuar.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
