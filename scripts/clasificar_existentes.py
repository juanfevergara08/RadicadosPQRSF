"""Clasifica y pone metadatos a documentos YA subidos en un radicado.

    python scripts/clasificar_existentes.py --confirmar --radicado CCPE26-5223

No sube nada. Solo clasifica las filas de "Documentos Base" y les pone
metadatos. Útil cuando la subida funcionó pero la clasificación falló.
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
    abrir_contexto,
    esperar_frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"
SELECT_TIPODOC = "#selectTipoDocumental"
TABLA_BASE = "#tabla_documentos"
TABLA_CLASIFICADOS = "#tbl_docs_clasificados"


def captura(pagina, marca: str, paso: str) -> None:
    try:
        pagina.screenshot(path=str(SALIDA / f"{marca}_{paso}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def esperar_procesando(marco, timeout_ms: int = 120000) -> None:
    transcurrido = 0
    while transcurrido < timeout_ms:
        try:
            if marco.get_by_text("Por favor espere", exact=False).first.is_visible():
                marco.wait_for_timeout(900)
                transcurrido += 900
                continue
        except Exception:  # noqa: BLE001
            pass
        return


def filas(marco, tabla: str) -> list:
    loc = marco.locator(f"{tabla} tr")
    return [loc.nth(i) for i in range(loc.count())]


def fila_de(marco, tabla: str, fragmento: str):
    from radicados.nombres import normalizar

    # DocxFlow reemplaza tildes por "_", así que "transacción" queda
    # "transacci_n" y pierde una letra. Se compara un prefijo corto.
    objetivo = normalizar(fragmento)[:12]
    for fila in filas(marco, tabla):
        try:
            if objetivo and objetivo in normalizar(fila.inner_text()):
                return fila
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--radicado", required=True)
    parser.add_argument(
        "--clasificar",
        nargs="*",
        default=[],
        help="pares fragmento=tipoDocumental",
    )
    parser.add_argument("--headless", action="store_true")
    argumentos = parser.parse_args()

    if not argumentos.confirmar:
        print("Ejecuta: python scripts/clasificar_existentes.py --confirmar --radicado CCPE26-XXXX")
        return 2

    pares = []
    for item in argumentos.clasificar:
        if "=" not in item:
            print(f"[FALLO] formato inválido: {item!r} (usa fragmento=tipo)")
            return 1
        fragmento, tipo = item.split("=", 1)
        pares.append((fragmento, tipo))

    if not pares:
        print("[FALLO] no indicaste --clasificar")
        return 1

    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    hoy = date.today().isoformat()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=argumentos.headless, slow_mo=70)
        contexto = abrir_contexto(navegador, SALIDA / "sesion.json")
        pagina = contexto.new_page()

        print("1. Autenticando")
        iniciar_sesion(pagina, config)
        guardar_sesion(contexto, SALIDA / "sesion.json")

        print("2. Abriendo radicado")
        marco = esperar_frame_contenido(pagina)
        if marco.locator("#actviadorBusqueda").count():
            marco.locator("#actviadorBusqueda").click()
            pagina.wait_for_timeout(900)
        marco.locator("#rad").fill(argumentos.radicado)
        marco.locator("#btn_buscar").click()
        pagina.wait_for_timeout(3500)
        marco = esperar_frame_contenido(pagina)
        marco.locator("tr", has_text=argumentos.radicado).first.get_by_role(
            "link", name="Registrar", exact=True
        ).first.click(timeout=20000)
        pagina.wait_for_timeout(4000)
        marco = esperar_frame_contenido(pagina)
        print(f"   abierto: {marco.locator('#ventanilla_radicacion_codigoRadicacion').input_value()}")

        print("3. Paso 3")
        for _ in range(2):
            marco.locator("#link_next").click(timeout=15000)
            pagina.wait_for_timeout(2000)
        captura(pagina, marca, "01_paso3")

        print("4. Clasificando")
        # Cerrar diálogos que hayan quedado abiertos de una corrida anterior
        try:
            while marco.locator(".ui-dialog:visible").count():
                marco.locator(".ui-dialog:visible").first.get_by_role(
                    "button", name="Cancelar"
                ).click(timeout=5000)
                pagina.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass

        for fragmento, tipo in pares:
            fila = fila_de(marco, TABLA_BASE, fragmento)
            if fila is None:
                print(f"   [AVISO] no encontré {fragmento!r} en Documentos Base")
                continue
            try:
                fila.get_by_text("Clasificar", exact=False).first.click(timeout=20000)
                pagina.wait_for_timeout(2500)

                select = marco.locator("#selectTipoDocumental:visible").first
                select.wait_for(state="visible", timeout=20000)
                select.select_option(label=tipo)

                marco.locator("#botAceptar:visible").first.click(timeout=20000)
                pagina.wait_for_timeout(3000)
                esperar_procesando(marco)
                print(f"   {fragmento[:40]!r} -> {tipo!r}")
            except Exception as error:  # noqa: BLE001
                print(f"   [FALLO] {fragmento[:30]!r}: {str(error).splitlines()[0][:90]}")
                try:
                    marco.locator("#botCancelar:visible").first.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
        captura(pagina, marca, "02_clasificados")

        print("5. Metadatos")
        for fragmento, tipo in pares:
            for _ in range(15):
                fila = fila_de(marco, TABLA_CLASIFICADOS, fragmento)
                if fila is not None:
                    break
                pagina.wait_for_timeout(1000)
            else:
                print(f"   [AVISO] {fragmento[:30]!r} no está en clasificados")
                continue
            try:
                fila.get_by_text("Metadatos", exact=False).first.click(timeout=20000)
                pagina.wait_for_timeout(2500)
                etiqueta = marco.locator("label", has_text="Fecha de creaci").first
                etiqueta.wait_for(state="visible", timeout=20000)
                destino = etiqueta.get_attribute("for")
                campo = marco.locator(f"#{destino}")
                campo.fill(hoy)
                campo.dispatch_event("change")
                campo.blur()
                marco.locator("#registrar_metadatos").click(timeout=25000)
                pagina.wait_for_timeout(4000)
                print(f"   metadatos: {fragmento[:40]!r}")
            except Exception as error:  # noqa: BLE001
                print(f"   [FALLO] metadatos {fragmento[:30]!r}: {str(error).splitlines()[0][:90]}")
        captura(pagina, marca, "03_metadatos")

        print("6. Guardando borrador")
        try:
            marco.locator("#link_save a").first.click(timeout=15000)
        except Exception:  # noqa: BLE001
            marco.locator("#link_save").click(timeout=15000)
        pagina.wait_for_timeout(5000)
        captura(pagina, marca, "04_borrador")

        print("7. Sin despachar")
        navegador.close()

    print(f"\nCapturas en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
