"""Carga un adjunto en un radicado existente de DocxFlow (paso 3).

    python scripts/cargar_anexo.py --confirmar --radicado CCPE26-7513

Flujo verificado con el usuario:
  1. Abre el radicado por la lupa de la bandeja y pulsa Registrar
  2. Paso 2: escribe el cuerpo del correo en el Asunto
  3. Paso 3: tipo de soporte = Electrónico
  4. Desmarca "Documento transformable PDF/A" (si no, no deja subir)
  5. Sube el archivo
  6. Pulsa Clasificar -> elige "Anexos" -> Aceptar
  7. Pulsa Metadatos -> Fecha de creación = hoy
  8. Pulsa "Guardar Documento"
  9. Guarda el borrador con el disquete (#link_save)

NUNCA pulsa Despachar.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
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

CAMPO_ASUNTO = "#ventanilla_radicacion_asunto"
CAMPO_SOPORTE = "#ventanilla_radicacion_tipoSoporte"
CASILLA_PDFA = "#ventanilla_radicacion_modificable"
CAMPO_ARCHIVO = "#file_upload"
SELECT_TIPODOC = "#selectTipoDocumental"


def captura(pagina, marca: str, paso: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def log_visibles(marco, etiqueta: str) -> None:
    """Lista botones y enlaces visibles: ayuda a depurar paso a paso."""
    try:
        textos = marco.evaluate(
            """() => [...document.querySelectorAll('button, a, input[type=button]')]
                .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
                .map(el => (el.innerText || el.value || '').trim())
                .filter(t => t && t.length < 40)"""
        )
        print(f"   [{etiqueta}] acciones visibles: {textos[:14]}")
    except Exception:  # noqa: BLE001
        pass


def esperar_texto(marco, texto: str, timeout_ms: int = 30000) -> bool:
    """Espera a que aparezca un elemento visible con ese texto."""
    transcurrido = 0
    while transcurrido < timeout_ms:
        try:
            localizador = marco.get_by_text(texto, exact=False)
            for indice in range(min(localizador.count(), 6)):
                if localizador.nth(indice).is_visible():
                    return True
        except Exception:  # noqa: BLE001
            pass
        marco.wait_for_timeout(500)
        transcurrido += 500
    return False


def escribir(marco, selector: str, valor: str) -> None:
    campo = marco.locator(selector)
    campo.wait_for(state="visible", timeout=20000)
    campo.fill(valor)
    campo.dispatch_event("change")
    campo.blur()
    marco.wait_for_timeout(400)


def abrir_radicado(pagina, marco, numero: str):
    if marco.locator("#actviadorBusqueda").count():
        marco.locator("#actviadorBusqueda").click()
        pagina.wait_for_timeout(900)
    marco.locator("#rad").fill(numero)
    marco.locator("#btn_buscar").click()
    pagina.wait_for_timeout(3500)
    marco = esperar_frame_contenido(pagina)

    marco.locator("tr", has_text=numero).first.get_by_role(
        "link", name="Registrar", exact=True
    ).first.click(timeout=20000)
    pagina.wait_for_timeout(4000)
    marco = esperar_frame_contenido(pagina)
    return marco


def esperar_procesando(marco, timeout_ms: int = 180000) -> bool:
    """Espera a que desaparezca el modal 'Procesando...' de la subida."""
    transcurrido = 0
    while transcurrido < timeout_ms:
        try:
            if marco.get_by_text("Por favor espere", exact=False).first.is_visible():
                marco.wait_for_timeout(1000)
                transcurrido += 1000
                continue
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def fila_con(marco, tabla: str, fragmento: str):
    """Primera fila de la tabla que contenga ese fragmento de nombre."""
    filas = marco.locator(f"{tabla} tr")
    for indice in range(filas.count()):
        try:
            if fragmento.lower() in filas.nth(indice).inner_text().lower():
                return filas.nth(indice)
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", default="CCPE26-7513")
    parser.add_argument(
        "--adjunto",
        default="",
        help="ruta del adjunto; si se omite se toma el PDF que contenga 'comprobante'",
    )
    parser.add_argument("--cuerpo", default="var/adjuntos/cuerpo_correo.txt")
    parser.add_argument(
        "--despachar",
        action="store_true",
        help="pulsa Despachar al final y verifica el resultado (IRREVERSIBLE)",
    )
    parser.add_argument(
        "--sin-asunto", action="store_true", help="no tocar el asunto del radicado"
    )
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Carga un adjunto en un radicado existente. No despacha.")
        print("Ejecuta: python scripts/cargar_anexo.py --confirmar")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()

    if argumentos.adjunto:
        ruta_adjunto = RAIZ / argumentos.adjunto
    else:
        ruta_adjunto = None

    if ruta_adjunto is None or not ruta_adjunto.exists():
        carpeta = RAIZ / "var" / "adjuntos"
        candidatos = sorted(carpeta.glob("*.pdf"))
        preferidos = [c for c in candidatos if "comprobante" in c.name.lower()]
        elegidos = preferidos or candidatos
        if not elegidos:
            print(f"[FALLO] no hay adjuntos en {carpeta}")
            print("Corre primero: python scripts/extraer_correo_prueba.py "
                  "--buscar \"CORREO DE PRUEBA\"")
            return 1
        ruta_adjunto = elegidos[-1]

    print(f"Adjunto: {ruta_adjunto.name} ({ruta_adjunto.stat().st_size} bytes)")

    cuerpo = ""
    ruta_cuerpo = RAIZ / argumentos.cuerpo
    if not argumentos.sin_asunto and ruta_cuerpo.exists():
        cuerpo = ruta_cuerpo.read_text(encoding="utf-8").strip()
        print(f"Asunto: {len(cuerpo)} caracteres del cuerpo del correo")

    hoy = date.today().isoformat()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 84)
    print(f"CARGAR ANEXO EN {argumentos.radicado}")
    print(f"  tipo de soporte .... Electrónico")
    print(f"  clasificación ...... Anexos")
    print(f"  fecha de creación .. {hoy}")
    print("  NO se despacha")
    print("=" * 84)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless, slow_mo=80)
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

        print("\n3. Abriendo el radicado")
        marco = esperar_frame_contenido(pagina)
        marco = abrir_radicado(pagina, marco, argumentos.radicado)
        print(f"   abierto: {marco.locator('#ventanilla_radicacion_codigoRadicacion').input_value()!r}")

        print("\n4. Paso 2 — Asunto")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2000)
        if cuerpo:
            escribir(marco, CAMPO_ASUNTO, cuerpo)
            print(f"   asunto escrito ({len(cuerpo)} caracteres)")
        captura(pagina, marca, "01_asunto")

        print("\n5. Paso 3 — Documento y anexos")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2500)
        log_visibles(marco, "paso 3")

        try:
            marco.locator(CAMPO_SOPORTE).select_option(value="2")
            print("   tipo de soporte: Electrónico (2)")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] tipo de soporte: {str(error).splitlines()[0][:80]}")

        try:
            casilla = marco.locator(CASILLA_PDFA)
            if casilla.is_checked():
                casilla.uncheck()
                print("   PDF/A desmarcado")
            else:
                print("   PDF/A ya estaba desmarcado")
            pagina.wait_for_timeout(800)
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] casilla PDF/A: {str(error).splitlines()[0][:80]}")

        print("\n6. Subiendo el archivo")
        marco.locator(CAMPO_ARCHIVO).set_input_files(str(ruta_adjunto))
        print("   archivo entregado al input; esperando el procesamiento...")
        esperar_procesando(marco, timeout_ms=180000)
        pagina.wait_for_timeout(2000)
        print("   procesamiento terminado")
        captura(pagina, marca, "02_subido")

        fragmento = ruta_adjunto.stem[:16]
        print(f"   buscando la fila del archivo ({fragmento!r})")

        print("\n7. Clasificando")
        fila = None
        for _ in range(20):
            fila = fila_con(marco, "#tabla_documentos", fragmento)
            if fila is not None:
                break
            pagina.wait_for_timeout(1000)

        if fila is None:
            print("   [FALLO] el archivo no aparece en Documentos Base")
            captura(pagina, marca, "error_sin_fila")
            navegador.close()
            return 1

        print(f"   fila encontrada: {fila.inner_text()[:90]!r}")
        try:
            fila.get_by_text("Clasificar", exact=False).first.click(timeout=15000)
            pagina.wait_for_timeout(2500)
            print("   clic en Clasificar de esa fila")
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] Clasificar: {str(error).splitlines()[0][:110]}")
            captura(pagina, marca, "error_clasificar")
            navegador.close()
            return 1

        captura(pagina, marca, "03_dialogo_clasificacion")
        try:
            marco.locator(SELECT_TIPODOC).wait_for(state="visible", timeout=20000)
            opciones = marco.locator(f"{SELECT_TIPODOC} option").all_inner_texts()
            print(f"   opciones disponibles: {[o.strip() for o in opciones][:8]}")
            marco.locator(SELECT_TIPODOC).select_option(label="Anexos")
            print("   clasificación: Anexos")
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] selector tipo documental: {str(error).splitlines()[0][:110]}")
            captura(pagina, marca, "error_select_tipodoc")
            navegador.close()
            return 1

        try:
            marco.locator("#botAceptar").click(timeout=15000)
            pagina.wait_for_timeout(4000)
            print("   Aceptar pulsado")
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] Aceptar: {str(error).splitlines()[0][:110]}")
            navegador.close()
            return 1

        esperar_procesando(marco, timeout_ms=60000)
        captura(pagina, marca, "04_clasificado")

        print("\n8. Metadatos — fecha de creación")
        fila_clasificada = None
        for _ in range(20):
            fila_clasificada = fila_con(marco, "#tbl_docs_clasificados", fragmento)
            if fila_clasificada is not None:
                break
            pagina.wait_for_timeout(1000)

        if fila_clasificada is None:
            print("   [FALLO] el archivo no aparece en Documentos clasificados")
            captura(pagina, marca, "error_sin_clasificado")
            navegador.close()
            return 1

        print(f"   fila clasificada: {fila_clasificada.inner_text()[:90]!r}")
        try:
            fila_clasificada.get_by_text("Metadatos", exact=False).first.click(timeout=15000)
            pagina.wait_for_timeout(3000)
            print("   clic en Metadatos de esa fila")
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] Metadatos: {str(error).splitlines()[0][:110]}")
            captura(pagina, marca, "error_metadatos")
            navegador.close()
            return 1

        captura(pagina, marca, "05_metadatos")
        try:
            etiqueta = marco.locator("label", has_text="Fecha de creaci").first
            etiqueta.wait_for(state="visible", timeout=20000)
            destino_id = etiqueta.get_attribute("for")
            print(f"   campo de fecha: {destino_id!r}")
            if destino_id:
                escribir(marco, f"#{destino_id}", hoy)
                valor = marco.locator(f"#{destino_id}").input_value()
                print(f"   fecha escrita: {valor!r}")
                if not valor.strip():
                    marco.locator(f"#{destino_id}").fill(hoy.replace("-", "/"))
                    print(f"   reintento: {marco.locator(f'#{destino_id}').input_value()!r}")
        except Exception as error:  # noqa: BLE001
            print(f"   [AVISO] fecha de creación: {str(error).splitlines()[0][:100]}")

        captura(pagina, marca, "06_fecha")

        print("\n9. Guardar Documento")
        try:
            marco.locator("#registrar_metadatos").click(timeout=20000)
            pagina.wait_for_timeout(5000)
            print("   Guardar Documento pulsado")
        except Exception as error:  # noqa: BLE001
            print(f"   [AVISO] Guardar Documento: {str(error).splitlines()[0][:110]}")
        captura(pagina, marca, "07_guardado_documento")

        print("\n10. Guardando el borrador (disquete)")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
            print("   disquete pulsado")
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
            print("   disquete pulsado (contenedor)")
        pagina.wait_for_timeout(6000)
        captura(pagina, marca, "08_borrador")

        if not argumentos.despachar:
            print("\n11. Comprobando Despachar (no se pulsa)")
            try:
                if marco.locator("#enviar-formulario").count():
                    print("   'Despachar' presente — NO se ha pulsado")
            except Exception:  # noqa: BLE001
                pass
            captura(pagina, marca, "09_final")
            navegador.close()
            print(f"\nCapturas en {SALIDA}")
            print("Revisa el radicado en DocxFlow. No se despachó.")
            return 0

        print("\n11. DESPACHANDO (irreversible)")
        try:
            marco.locator("#enviar-formulario").click(timeout=25000)
            print("   Despachar pulsado")
        except Exception as error:  # noqa: BLE001
            print(f"   [FALLO] Despachar: {str(error).splitlines()[0][:120]}")
            captura(pagina, marca, "error_despachar")
            navegador.close()
            return 1

        pagina.wait_for_timeout(9000)
        captura(pagina, marca, "10_despachado")

        print("\n12. Verificando el resultado")
        marco = esperar_frame_contenido(pagina)
        try:
            cuerpo_pantalla = marco.inner_text("body")
            for clave in ("exit", "despach", "radicad", "error", "fall", "asignad"):
                for linea in cuerpo_pantalla.splitlines():
                    if clave in linea.lower() and linea.strip():
                        print(f"   aviso: {linea.strip()[:110]}")
                        break
        except Exception:  # noqa: BLE001
            print("   [aviso] no se pudo leer la pantalla")

        print(f"   url tras despachar: {marco.url[:90]}")

        # Comprobación real: ¿sigue pendiente en documentos de entrada?
        try:
            if marco.locator("#actviadorBusqueda").count():
                marco.locator("#actviadorBusqueda").click()
                pagina.wait_for_timeout(900)
                marco.locator("#rad").fill(argumentos.radicado)
                marco.locator("#btn_buscar").click()
                pagina.wait_for_timeout(4000)
                marco = esperar_frame_contenido(pagina)
                sigue = argumentos.radicado in marco.inner_text("body")
                if sigue:
                    print(f"   [ATENCIÓN] {argumentos.radicado} AÚN aparece en la bandeja")
                else:
                    print(f"   OK: {argumentos.radicado} ya no está pendiente en la bandeja")
                captura(pagina, marca, "11_verificacion_bandeja")
            else:
                print("   no hay buscador en esta pantalla para verificar")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] verificación de bandeja: {str(error).splitlines()[0][:100]}")

        captura(pagina, marca, "12_final")
        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    print("Revisa el resultado en DocxFlow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
