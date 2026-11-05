"""Carga múltiples adjuntos en un radicado existente de DocxFlow.

Uso:
    python scripts/cargar_anexo_multi.py --confirmar --radicado CCPE26-5223

Flujo:
  1. Login + rol de ventanilla única
  2. Busca el radicado en la bandeja y abre "Registrar"
  3. Paso 2: escribe el asunto del correo
  4. Paso 3: tipo de soporte = Electrónico, desmarca PDF/A
  5. Para cada adjunto:
     a. Sube el archivo
     b. Clasifica con su tipo documental específico
     c. Pone metadatos (fecha de creación) y guarda documento
  6. Paso 4: selecciona tipo de trámite (derechos de petición)
  7. Paso 5: distribución = Envío directo
  8. Guarda borrador con el disquete (#link_save)
  9. NO despacha
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402
from radicados.docxflow_rpa import (  # noqa: E402
    ErrorLogin,
    abrir_contexto,
    esperar_frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)
from radicados.nombres import prefijo_de, coincide  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"

CAMPO_ASUNTO = "#ventanilla_radicacion_asunto"
CAMPO_SOPORTE = "#ventanilla_radicacion_tipoSoporte"
CASILLA_PDFA = "#ventanilla_radicacion_modificable"
CAMPO_ARCHIVO = "#file_upload"
SELECT_TIPODOC = "#selectTipoDocumental"
CAMPO_TRAMITE = "#ventanilla_radicacion_tramite"
CAMPO_UNIDAD = "#ventanilla_radicacion_unidadDistribucion"
CAMPO_RADICADO = "#ventanilla_radicacion_codigoRadicacion"
CAMPO_REFERENCIA = "#ventanilla_radicacion_referencia"

TABLA_BASE = "#tabla_documentos"
TABLA_CLASIFICADOS = "#tbl_docs_clasificados"


# --------------------------------------------------------------------- utils


def captura(pagina, marca: str, paso: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def esperar_procesando(marco, timeout_ms: int = 240000) -> bool:
    transcurrido = 0
    while transcurrido < timeout_ms:
        try:
            if marco.get_by_text("Por favor espere", exact=False).first.is_visible():
                marco.wait_for_timeout(900)
                transcurrido += 900
                continue
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def filas_de(marco, tabla: str) -> list:
    localizador = marco.locator(f"{tabla} tr")
    return [localizador.nth(i) for i in range(localizador.count())]


def fila_por_prefijo(marco, tabla: str, prefijo: str, evitar: set[str] | None = None):
    evitar = evitar or set()
    for fila in filas_de(marco, tabla):
        try:
            texto = fila.inner_text()
        except Exception:  # noqa: BLE001
            continue
        from radicados.nombres import normalizar as _norm

        if prefijo in _norm(texto) and texto not in evitar:
            return fila
    return None


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
    return esperar_frame_contenido(pagina)


# --------------------------------------------------------------------- pasos


def subir_archivo(marco, pagina, ruta: Path) -> str:
    """Sube un archivo y devuelve el prefijo normalizado para buscarlo después."""
    print(f"   subiendo {ruta.name} ({ruta.stat().st_size} bytes)")
    antes = len(filas_de(marco, TABLA_BASE))
    marco.locator(CAMPO_ARCHIVO).set_input_files(str(ruta))
    esperar_procesando(marco)
    pagina.wait_for_timeout(1500)
    for _ in range(20):
        despues = len(filas_de(marco, TABLA_BASE))
        if despues > antes:
            print(f"      ok: tabla pasó de {antes} a {despues} filas")
            return prefijo_de(ruta)
        pagina.wait_for_timeout(1000)
    print(f"      [AVISO] no creció la tabla")
    return ""


def clasificar_archivo(marco, pagina, prefijo: str, tipo_documental: str, nombre: str) -> bool:
    fila = fila_por_prefijo(marco, TABLA_BASE, prefijo)
    if fila is None:
        print(f"      [AVISO] no se encontró la fila de {nombre}")
        return False
    fila.get_by_text("Clasificar", exact=False).first.click(timeout=20000)
    pagina.wait_for_timeout(2000)
    marco.locator(SELECT_TIPODOC).wait_for(state="visible", timeout=20000)
    try:
        marco.locator(SELECT_TIPODOC).select_option(label=tipo_documental)
    except Exception as error:  # noqa: BLE001
        print(f"      [AVISO] no se pudo seleccionar '{tipo_documental}': {error}")
        return False
    marco.locator("#botAceptar").click(timeout=20000)
    pagina.wait_for_timeout(3000)
    esperar_procesando(marco, timeout_ms=60000)
    print(f"      {nombre}: clasificado como '{tipo_documental}'")
    return True


def poner_metadatos(marco, pagina, prefijo: str, nombre: str, hoy: str) -> bool:
    for _ in range(15):
        fila = fila_por_prefijo(marco, TABLA_CLASIFICADOS, prefijo)
        if fila is not None:
            break
        pagina.wait_for_timeout(1000)
    else:
        print(f"      [AVISO] {nombre} no aparece en clasificados")
        return False
    fila.get_by_text("Metadatos", exact=False).first.click(timeout=20000)
    pagina.wait_for_timeout(2500)
    etiqueta_fecha = marco.locator("label", has_text="Fecha de creaci").first
    etiqueta_fecha.wait_for(state="visible", timeout=20000)
    destino = etiqueta_fecha.get_attribute("for")
    if not destino:
        print("      [AVISO] no se encontró el campo de fecha")
        return False
    escribir(marco, f"#{destino}", hoy)
    marco.locator("#registrar_metadatos").click(timeout=25000)
    pagina.wait_for_timeout(4000)
    print(f"      {nombre}: metadatos y Guardar Documento")
    return True


# ----------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    parser.add_argument(
        "--adjuntos",
        nargs="*",
        default=[],
        help="rutas de los archivos",
    )
    parser.add_argument("--tipos-documentales",
                        nargs="*",
                        default=[],
                        help="tipos documentales en el mismo orden que los adjuntos")
    parser.add_argument("--cuerpo", default="var/adjuntos/cuerpo_correo.txt")
    parser.add_argument("--asunto", default="")
    parser.add_argument("--tramite", default="derechos de peticion")
    parser.add_argument("--despachar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Carga adjuntos en un radicado. No despacha salvo --despachar.")
        print("Ejecuta: python scripts/cargar_anexo_multi.py --confirmar --radicado CCPE26-XXXX")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()

    if argumentos.adjuntos:
        rutas = [
            (RAIZ / a) if not Path(a).is_absolute() else Path(a)
            for a in argumentos.adjuntos
        ]
        faltan = [r for r in rutas if not r.exists()]
        if faltan:
            print("[FALLO] no existen estos adjuntos:")
            for r in faltan:
                print(f"   {r}")
            return 1
    else:
        carpeta = RAIZ / "var" / "adjuntos"
        rutas = sorted(carpeta.glob("*.pdf"), key=lambda p: p.name)
        if not rutas:
            print("[FALLO] no hay PDF en var/adjuntos/")
            print("Corre: python scripts/extraer_frisby.py --confirmar")
            return 1

    print(f"Adjuntos seleccionados: {len(rutas)}")

    tipos = argumentos.tipos_documentales
    if len(tipos) < len(rutas):
        tipos = tipos + ["Anexos"] * (len(rutas) - len(tipos))

    cuerpo = ""
    ruta_cuerpo = RAIZ / argumentos.cuerpo
    if ruta_cuerpo.exists():
        cuerpo = ruta_cuerpo.read_text(encoding="utf-8").strip()
    if argumentos.asunto:
        cuerpo = argumentos.asunto

    hoy = date.today().isoformat()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 84)
    print(f"CARGAR {len(rutas)} ADJUNTO(S) EN {argumentos.radicado}")
    for i, (r, t) in enumerate(zip(rutas, tipos), 1):
        print(f"  {i}. {r.name} → '{t}'")
    print(f"  asunto ......... {cuerpo[:80] if cuerpo else '(vacío)'}")
    print(f"  trámite ........ {argumentos.tramite}")
    print(f"  fecha creación . {hoy}")
    print(f"  despachar ...... {'SÍ' if argumentos.despachar else 'no'}")
    print("=" * 84)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless, slow_mo=70)
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
        print(f"   abierto: {marco.locator(CAMPO_RADICADO).input_value()!r}")

        print("\n4. Paso 2 — Asunto")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2000)
        escribir(marco, CAMPO_ASUNTO, cuerpo)
        print(f"   asunto: {cuerpo[:80]}")
        captura(pagina, marca, "01_asunto")

        print("\n5. Paso 3 — Documento y anexos")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2500)
        marco.locator(CAMPO_SOPORTE).select_option(value="2")
        print("   tipo de soporte: Electrónico")
        try:
            casilla = marco.locator(CASILLA_PDFA)
            if casilla.is_checked():
                casilla.uncheck()
                print("   PDF/A desmarcado")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] PDF/A: {str(error).splitlines()[0][:80]}")

        print(f"\n6. Subiendo {len(rutas)} archivo(s)")
        subidos = []
        for indice, ruta in enumerate(rutas, 1):
            prefijo = subir_archivo(marco, pagina, ruta)
            subidos.append((ruta, prefijo, tipos[indice - 1]))
            captura(pagina, marca, f"02_subido_{indice}")

        print(f"\n7. Clasificando {len(subidos)} archivo(s)")
        for ruta, prefijo, tipo_doc in subidos:
            clasificar_archivo(marco, pagina, prefijo, tipo_doc, ruta.name)
        captura(pagina, marca, "04_clasificados")

        print(f"\n8. Metadatos de {len(subidos)} archivo(s)")
        for ruta, prefijo, tipo_doc in subidos:
            poner_metadatos(marco, pagina, prefijo, ruta.name, hoy)
        captura(pagina, marca, "07_metadatos")

        print("\n9. Paso 4 — tipo de trámite")
        try:
            marco.locator("#link_next").click(timeout=15000)
            pagina.wait_for_timeout(2000)
            marco.locator("#ventanilla_radicacion_formaEnvioRespuesta").select_option(
                value="correo_electronico"
            )
            marco.locator("#ventanilla_radicacion_tramite").select_option(
                value=argumentos.tramite
            )
            elegido = marco.locator("#ventanilla_radicacion_tramite").evaluate(
                "el => el.options[el.selectedIndex].text"
            )
            print(f"   trámite: {elegido!r} (value={argumentos.tramite})")
            captura(pagina, marca, "08_tramite")
        except Exception as error:  # noqa: BLE001
            print(f"   [AVISO] trámite: {str(error).splitlines()[0][:100]}")

        print("\n10. Guardando el borrador (disquete)")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
        pagina.wait_for_timeout(5000)
        print("   borrador guardado")
        captura(pagina, marca, "09_borrador")

        if argumentos.despachar:
            print("\n10. DESPACHANDO (irreversible)")
            try:
                marco.locator("#enviar-formulario").click(timeout=25000)
            except Exception as error:  # noqa: BLE001
                print(f"   [FALLO] Despachar: {str(error).splitlines()[0][:110]}")
                captura(pagina, marca, "error_despachar")
                navegador.close()
                return 1
            pagina.wait_for_timeout(9000)
            captura(pagina, marca, "10_despachado")
        else:
            print("\n10. Sin despachar (modo revisión)")

        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
