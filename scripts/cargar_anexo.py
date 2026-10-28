"""Carga N adjuntos en un radicado de DocxFlow (paso 3), clasifica y despacha.

    # 1) Varios archivos concretos
    python scripts/cargar_anexo.py --confirmar --radicado CCPE26-7513 ^
        --adjuntos var/adjuntos/a.pdf var/adjuntos/b.pdf

    # 2) Todos los PDF de la carpeta (por defecto)
    python scripts/cargar_anexo.py --confirmar --radicado CCPE26-7513

    # 3) Con despacho al final
    python scripts/cargar_anexo.py --confirmar --radicado CCPE26-XXXX --despachar

Flujo por cada archivo:
  1. Tipo de soporte = Electrónico
  2. Desmarcar "Documento transformable PDF/A"
  3. Subir y esperar el modal "Procesando"
  Luego, por cada fila:
  4. Clasificar -> "Anexos" -> Aceptar
  5. Metadatos -> Fecha de creación -> Guardar Documento
  Al final:
  6. Disquete (borrador) y, si se pide, Despachar
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
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
from radicados.nombres import coincide, prefijo_de  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"

CAMPO_ASUNTO = "#ventanilla_radicacion_asunto"
CAMPO_SOPORTE = "#ventanilla_radicacion_tipoSoporte"
CASILLA_PDFA = "#ventanilla_radicacion_modificable"
CAMPO_ARCHIVO = "#file_upload"
SELECT_TIPODOC = "#selectTipoDocumental"
TABLA_BASE = "#tabla_documentos"
TABLA_CLASIFICADOS = "#tbl_docs_clasificados"


# --------------------------------------------------------------------- utils


def captura(pagina, marca: str, paso: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def normalizar(texto: str) -> str:
    """Sin tildes, sin espacios ni símbolos: sirve para comparar nombres."""
    from radicados.nombres import normalizar as _normalizar

    return _normalizar(texto)


def esperar_procesando(marco, timeout_ms: int = 240000) -> bool:
    """Espera a que desaparezca el modal 'Procesando...' de la subida."""
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
    """Primera fila cuyo texto normalizado empiece por el prefijo."""
    evitar = evitar or set()
    for fila in filas_de(marco, tabla):
        try:
            texto = fila.inner_text()
        except Exception:  # noqa: BLE001
            continue
        if prefijo in normalizar(texto) and texto not in evitar:
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


def subir(marco, pagina, ruta: Path, indice: int, total: int) -> bool:
    print(f"   [{indice}/{total}] subiendo {ruta.name} ({ruta.stat().st_size} bytes)")
    antes = len(filas_de(marco, TABLA_BASE))

    marco.locator(CAMPO_ARCHIVO).set_input_files(str(ruta))
    esperar_procesando(marco)
    pagina.wait_for_timeout(1500)

    for _ in range(20):
        despues = len(filas_de(marco, TABLA_BASE))
        if despues > antes:
            print(f"      ok: la tabla pasó de {antes} a {despues} filas")
            return True
        pagina.wait_for_timeout(1000)

    print(f"      [AVISO] no creció la tabla (sigue en {antes} filas)")
    return False


def clasificar(marco, pagina, prefijo: str, etiqueta: str) -> bool:
    fila = fila_por_prefijo(marco, TABLA_BASE, prefijo)
    if fila is None:
        print(f"      [AVISO] no se encontró la fila de {etiqueta} para clasificar")
        return False

    fila.get_by_text("Clasificar", exact=False).first.click(timeout=20000)
    pagina.wait_for_timeout(2000)
    marco.locator(SELECT_TIPODOC).wait_for(state="visible", timeout=20000)
    marco.locator(SELECT_TIPODOC).select_option(label="Anexos")
    marco.locator("#botAceptar").click(timeout=20000)
    pagina.wait_for_timeout(3000)
    esperar_procesando(marco, timeout_ms=60000)
    print(f"      {etiqueta}: clasificado como Anexos")
    return True


def poner_metadatos(marco, pagina, prefijo: str, etiqueta: str, hoy: str) -> bool:
    for _ in range(15):
        fila = fila_por_prefijo(marco, TABLA_CLASIFICADOS, prefijo)
        if fila is not None:
            break
        pagina.wait_for_timeout(1000)
    else:
        print(f"      [AVISO] {etiqueta} no aparece en clasificados")
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
    print(f"      {etiqueta}: metadatos y Guardar Documento")
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
        help="rutas de los archivos; si se omite se usan los PDF de var/adjuntos",
    )
    parser.add_argument("--cuerpo", default="var/adjuntos/cuerpo_correo.txt")
    parser.add_argument("--sin-asunto", action="store_true")
    parser.add_argument("--despachar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Carga adjuntos en un radicado. No despacha salvo --despachar.")
        print("Ejecuta: python scripts/cargar_anexo.py --confirmar --radicado CCPE26-XXXX")
        return 2

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()

    rutas: list[Path] = []
    if argumentos.adjuntos:
        rutas = [RAIZ / a if not Path(a).is_absolute() else Path(a) for a in argumentos.adjuntos]
    else:
        carpeta = RAIZ / "var" / "adjuntos"
        rutas = sorted(carpeta.glob("*.pdf"))

    rutas = [r for r in rutas if r.exists()]
    if not rutas:
        print("[FALLO] no hay adjuntos para subir")
        print('Corre: python scripts/extraer_correo_prueba.py --buscar "CORREO DE PRUEBA"')
        return 1

    cuerpo = ""
    ruta_cuerpo = RAIZ / argumentos.cuerpo
    if not argumentos.sin_asunto and ruta_cuerpo.exists():
        cuerpo = ruta_cuerpo.read_text(encoding="utf-8").strip()

    hoy = date.today().isoformat()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 84)
    print(f"CARGAR {len(rutas)} ADJUNTO(S) EN {argumentos.radicado}")
    for i, r in enumerate(rutas, 1):
        print(f"  {i}. {r.name}")
    print(f"  asunto ......... {len(cuerpo)} caracteres")
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
        print(f"   abierto: {marco.locator('#ventanilla_radicacion_codigoRadicacion').input_value()!r}")

        print("\n4. Paso 2 — Asunto")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2000)
        if cuerpo:
            escribir(marco, CAMPO_ASUNTO, cuerpo)
            print(f"   asunto escrito ({len(cuerpo)} caracteres)")

        print("\n5. Paso 3 — configurar soporte")
        marco.locator("#link_next").click(timeout=15000)
        pagina.wait_for_timeout(2500)
        marco.locator(CAMPO_SOPORTE).select_option(value="2")
        print("   tipo de soporte: Electrónico")
        try:
            casilla = marco.locator(CASILLA_PDFA)
            if casilla.is_checked():
                casilla.uncheck()
                print("   PDF/A desmarcado")
            else:
                print("   PDF/A ya estaba desmarcado")
        except Exception as error:  # noqa: BLE001
            print(f"   [aviso] PDF/A: {str(error).splitlines()[0][:80]}")

        print(f"\n6. Subiendo {len(rutas)} archivo(s)")
        subidos: list[tuple[Path, str]] = []
        for indice, ruta in enumerate(rutas, 1):
            prefijo = prefijo_de(ruta)
            if subir(marco, pagina, ruta, indice, len(rutas)):
                subidos.append((ruta, prefijo))
            captura(pagina, marca, f"02_subido_{indice}")

        if not subidos:
            print("[FALLO] no se subió ningún archivo")
            captura(pagina, marca, "error_sin_subidas")
            navegador.close()
            return 1

        print(f"\n7. Clasificando {len(subidos)} archivo(s)")
        for ruta, prefijo in subidos:
            clasificar(marco, pagina, prefijo, ruta.name)
        captura(pagina, marca, "04_clasificados")

        print(f"\n8. Metadatos de {len(subidos)} archivo(s)")
        for ruta, prefijo in subidos:
            poner_metadatos(marco, pagina, prefijo, ruta.name, hoy)
        captura(pagina, marca, "07_metadatos")

        print("\n9. Guardando el borrador (disquete)")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
        pagina.wait_for_timeout(5000)
        print("   borrador guardado")
        captura(pagina, marca, "08_borrador")

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

            print("\n11. Verificando")
            try:
                cuerpo_pantalla = marco.inner_text("body")
                for linea in cuerpo_pantalla.splitlines():
                    bajo = linea.lower()
                    if any(k in bajo for k in ("exit", "despach", "error", "fall")):
                        if linea.strip():
                            print(f"   aviso: {linea.strip()[:100]}")
            except Exception:  # noqa: BLE001
                pass
            print(f"   url: {marco.url[:90]}")
            captura(pagina, marca, "12_final")
        else:
            print("\n10. Sin despachar (modo revisión)")

        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
