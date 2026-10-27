"""Completa y guarda un radicado existente en DocxFlow, sin despacharlo.

    python scripts/actualizar_radicado.py --confirmar --radicado CCPE26-7513

Flujo:
  1. Login + rol de ventanilla única
  2. Busca el radicado en la bandeja (#rad + #btn_buscar)
  3. Clic en "Registrar" de esa fila
  4. Llena remitente, destinatario, asunto (paso 2)
  5. Llena trámite y forma de envío (paso 4)
  6. Deja "Envío directo *" y transporte digital (paso 5)
  7. Guarda con el disquete (#link_save -> guardarRegistro)
  8. NUNCA pulsa Despachar (#enviar-formulario)
"""

from __future__ import annotations

import argparse
import re
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
CAMPO_ENVIO_RESP = "#ventanilla_radicacion_formaEnvioRespuesta"
CAMPO_TRANSPORTE = "#ventanilla_radicacion_tipoTransporteInterno"

MENU_AUTOCOMPLETE = "ul.ui-autocomplete:visible li"


def captura(pagina, marca: str, paso: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def elegir_autocompletado(
    marco, selector: str, termino: str, objetivo: str | None, etiqueta: str
) -> bool:
    """Escribe y elige la sugerencia con clic del ratón.

    Verificado en vivo: el clic sobre el <li> de la sugerencia es lo que
    dispara el handler de jQuery UI que fija el id interno (remitenteId /
    destinatarioId). Navegar con ArrowDown + Enter selecciona mal: muestra
    "Información de la entidad" y deja el id sin asignar.
    """
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
    print(f"      sugerencias: {textos[:4]}")

    indice = 0
    if objetivo:
        for posicion, texto in enumerate(textos):
            if objetivo.lower() in texto.lower():
                indice = posicion
                break

    opciones.nth(indice).click()
    marco.wait_for_timeout(1500)
    print(f"      elegido: {textos[indice][:70]}")
    return True


def leer_ids(marco) -> dict:
    """Lee los ids internos y los textos restaurados por DocxFlow."""
    return marco.evaluate(
        """() => {
            const textoInfo = (id) => {
                const el = document.getElementById(id);
                return el ? (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 90) : '';
            };
            const sel = (id) => {
                const el = document.getElementById(id);
                return el && el.options && el.selectedIndex >= 0
                    ? el.options[el.selectedIndex].text.trim() : '';
            };
            return {
                remitenteId: typeof remitenteId === 'undefined' ? null : remitenteId,
                destinatarioId: typeof destinatarioId === 'undefined' ? null : destinatarioId,
                remitenteInfo: textoInfo('remitente_info'),
                destinatarioInfo: textoInfo('destinatario_info'),
                asunto: (document.getElementById('ventanilla_radicacion_asunto') || {}).value || '',
                tramite: sel('ventanilla_radicacion_tramite'),
                unidad: sel('ventanilla_radicacion_unidadDistribucion'),
                envioRespuesta: sel('ventanilla_radicacion_formaEnvioRespuesta')
            };
        }"""
    )


def escribir(marco, selector: str, valor: str) -> None:
    """Escribe y dispara change/blur para que jQuery Validate lo registre."""
    campo = marco.locator(selector)
    campo.wait_for(state="visible", timeout=15000)
    campo.fill(valor)
    campo.dispatch_event("change")
    campo.blur()
    marco.wait_for_timeout(500)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", default="CCPE26-7513")
    parser.add_argument("--remitente", default="LUZ ENITH OSORIO OROZCO")
    parser.add_argument("--asunto", default="PRUEBAS RADICADOS")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--verificar",
        action="store_true",
        help="solo abrir y leer los campos guardados, sin escribir nada",
    )
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Actualiza un radicado existente. No despacha.")
        print("Ejecuta: python scripts/actualizar_radicado.py --confirmar")
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
    print(f"ACTUALIZAR RADICADO {argumentos.radicado}")
    print(f"  remitente ..... {argumentos.remitente}")
    print(f"  destinatario .. {destinatario}")
    print(f"  asunto ........ {argumentos.asunto}")
    print(f"  trámite ....... {tramite}")
    print("  guardado ...... disquete (#link_save). NO se despacha.")
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
                print(f"   rol: {actual or 'ventanilla'}")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] {str(error).splitlines()[0][:90]}")

        print("\n3. Buscando el radicado en la bandeja")
        marco = esperar_frame_contenido(pagina)
        captura(pagina, marca, "01_bandeja")

        encontrado = False
        for termino in (argumentos.radicado, argumentos.radicado.split("-")[-1]):
            try:
                # La barra de búsqueda está oculta hasta pulsar la lupa
                if marco.locator("#actviadorBusqueda").count():
                    marco.locator("#actviadorBusqueda").click()
                    pagina.wait_for_timeout(1000)
                if marco.locator("#rad").count():
                    marco.locator("#rad").fill(termino)
                    marco.locator("#btn_buscar").click()
                    pagina.wait_for_timeout(3500)
                    marco = esperar_frame_contenido(pagina)
                    texto = marco.inner_text("body")
                    if argumentos.radicado in texto:
                        print(f"   encontrado buscando {termino!r}")
                        encontrado = True
                        break
                    print(f"   sin resultados con {termino!r}")
            except Exception as error:  # noqa: BLE001
                print(f"   [aviso] búsqueda {termino!r}: {str(error).splitlines()[0][:80]}")

        if not encontrado:
            print("   [aviso] la búsqueda no confirmó el radicado; se usa la bandeja visible")

        captura(pagina, marca, "02_busqueda")

        print("\n4. Abriendo el registro")
        fila = marco.locator("tr", has_text=argumentos.radicado).first
        try:
            if fila.count():
                fila.get_by_role("link", name="Registrar", exact=True).first.click(timeout=15000)
            else:
                print("   [aviso] sin fila coincidente; se usa el primer 'Registrar'")
                marco.get_by_role("link", name="Registrar", exact=True).first.click(timeout=15000)
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] no se pudo abrir: {str(error).splitlines()[0][:110]}")
            captura(pagina, marca, "error_abrir")
            navegador.close()
            return 1

        pagina.wait_for_timeout(4000)
        marco = esperar_frame_contenido(pagina)
        numero_abierto = marco.locator(CAMPO_RADICADO).input_value()
        print(f"   abierto: {numero_abierto!r}  ({marco.url[-40:]})")

        if numero_abierto and numero_abierto != argumentos.radicado:
            print(f"   [AVISO] se abrió {numero_abierto}, no {argumentos.radicado}")
            print("   Se continúa: es el único registro abierto por la búsqueda.")

        captura(pagina, marca, "03_abierto")

        if argumentos.verificar:
            print("\n5. VERIFICACIÓN (solo lectura)")
            try:
                marco.locator("#link_next").click(timeout=15000)
                pagina.wait_for_timeout(2000)
            except Exception:  # noqa: BLE001
                pass
            datos = leer_ids(marco)
            print(f"   remitenteId .... {datos['remitenteId']}")
            print(f"   destinatarioId . {datos['destinatarioId']}")
            print(f"   remitente ...... {datos['remitenteInfo'][:90]}")
            print(f"   destinatario ... {datos['destinatarioInfo'][:90]}")
            print(f"   asunto ......... {datos['asunto']!r}")
            print(f"   trámite ........ {datos['tramite']!r}")
            print(f"   envío respuesta  {datos['envioRespuesta']!r}")
            print(f"   unidad ......... {datos['unidad']!r}")
            captura(pagina, marca, "09_verificacion")
            navegador.close()
            return 0

        print("\n5. Paso 2 — Información de correspondencia")
        try:
            marco.locator("#link_next").click(timeout=15000)
            pagina.wait_for_timeout(2000)
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] siguiente: {str(error).splitlines()[0][:90]}")

        if not elegir_autocompletado(
            marco, CAMPO_REMITENTE, argumentos.remitente, None, "Remitente"
        ):
            print("   [FALLO] sin remitente")
            captura(pagina, marca, "error_remitente")
            navegador.close()
            return 1

        elegir_autocompletado(
            marco, CAMPO_DESTINATARIO, destinatario, destinatario, "Destinatario"
        )

        escribir(marco, CAMPO_ASUNTO, argumentos.asunto)
        print(f"   asunto: {argumentos.asunto!r}")

        ids = leer_ids(marco)
        print(f"   ids internos -> remitenteId={ids['remitenteId']} "
              f"destinatarioId={ids['destinatarioId']}")
        if not ids["remitenteId"] or not ids["destinatarioId"]:
            print("   [AVISO] algún id quedó en 0; DocxFlow podría rechazar el guardado")
        else:
            print(f"   remitente:    {ids['remitenteInfo'][:80]}")
            print(f"   destinatario: {ids['destinatarioInfo'][:80]}")
        captura(pagina, marca, "04_correspondencia")

        print("\n6. Paso 4 — Trámite y forma de envío")
        for _ in range(2):
            marco.locator("#link_next").click(timeout=15000)
            pagina.wait_for_timeout(1800)
        try:
            marco.locator(CAMPO_ENVIO_RESP).select_option(value="correo_electronico")
            print("   forma de envío: correo_electronico")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] forma de envío: {str(error).splitlines()[0][:80]}")
        marco.locator(CAMPO_TRAMITE).select_option(value=tramite)
        print(f"   trámite: {tramite}")
        captura(pagina, marca, "05_tramite")

        print("\n7. Paso 5 — Distribución")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2000)
        try:
            marco.locator(CAMPO_UNIDAD).select_option(value="-1")
            print("   unidad: Envío directo * (-1)")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] unidad: {str(error).splitlines()[0][:80]}")
        captura(pagina, marca, "06_distribucion")

        print("\n8. Guardando con el disquete (#link_save)")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
            print("   clic en guardar")
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
            print("   clic en guardar (contenedor)")
        pagina.wait_for_timeout(6000)

        # Confirmación: buscar aviso de guardado
        try:
            cuerpo = marco.inner_text("body")
            for aviso in ("guardad", "exitos", "actualiz", "error", "fall"):
                if re.search(aviso, cuerpo, re.I):
                    linea = next(
                        (l.strip() for l in cuerpo.splitlines() if re.search(aviso, l, re.I)),
                        "",
                    )
                    print(f"   aviso en pantalla: {linea[:110]}")
        except Exception:  # noqa: BLE001
            pass

        captura(pagina, marca, "07_guardado")

        print("\n9. Comprobando 'Despachar' (NO se pulsa)")
        try:
            if marco.locator("#enviar-formulario").count():
                print("   'Despachar' presente — NO se ha pulsado")
        except Exception:  # noqa: BLE001
            pass

        captura(pagina, marca, "08_final")
        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    print("No se despachó. Revisa el radicado en DocxFlow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
