"""Exporta 'Documentos despachados' de DocxFlow a Excel.

    python scripts/exportar_despachados.py --confirmar

DocxFlow no tiene exportación, así que se lee la tabla del navegador.
No modifica nada en DocxFlow.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion
from radicados.docxflow_rpa import (
    abrir_contexto,
    esperar_frame_contenido,
    guardar_sesion,
    iniciar_sesion,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SALIDA = RAIZ / "var" / "rpa"
REPORTES = RAIZ / "var" / "reportes"

# Lee la tabla visible: encabezados y filas
JS_TABLA = """() => {
    const tablas = [...document.querySelectorAll('table')]
        .filter(t => { const r = t.getBoundingClientRect(); return r.width > 200 && r.height > 40; });
    if (!tablas.length) return null;
    let mejor = null, maxFilas = 0;
    for (const t of tablas) {
        const filas = t.querySelectorAll('tr').length;
        if (filas > maxFilas) { maxFilas = filas; mejor = t; }
    }
    const heads = [...mejor.querySelectorAll('thead th, tr:first-child th')]
        .map(th => th.innerText.trim());
    const filas = [...mejor.querySelectorAll('tbody tr')]
        .map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()));
    return { heads, filas };
}"""

JS_PAGINACION = """() => {
    const sels = [...document.querySelectorAll('select')].map(s => ({
        id: s.id, name: s.name,
        opciones: [...s.options].map(o => o.text.trim())
    }));
    const txt = document.body.innerText;
    const m = txt.match(/P[aá]gina\\s*(\\d+)\\s*de\\s*(\\d+)/i);
    return { sels, pagina: m ? Number(m[1]) : null, totalPaginas: m ? Number(m[2]) : null };
}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not args.confirmar:
        print("Ejecuta con --confirmar")
        return 2

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from playwright.sync_api import sync_playwright

    config = Configuracion.cargar()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    REPORTES.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=args.headless, slow_mo=70)
        ctx = abrir_contexto(nav, SALIDA / "sesion.json")
        pag = ctx.new_page()
        iniciar_sesion(pag, config)
        guardar_sesion(ctx, SALIDA / "sesion.json")

        print("1. Rol de ventanilla única de salida")
        pag.locator("#opcRol").select_option(label="Rol de ventanilla única de salida")
        pag.locator("#frmRol").evaluate("(f) => f.submit()")
        pag.wait_for_load_state("networkidle", timeout=40000)
        pag.wait_for_timeout(4000)

        print("2. Documentos de salida -> Documentos despachados")
        pag.get_by_text("Documentos de salida", exact=True).first.click(timeout=15000)
        pag.wait_for_timeout(2000)
        pag.get_by_text("Documentos despachados", exact=True).first.click(timeout=15000)
        pag.wait_for_timeout(5000)
        print(f"   url: {pag.url}")

        pag.screenshot(path=str(SALIDA / f"{marca}_despachados.png"), full_page=True)

        marco = esperar_frame_contenido(pag)
        print(f"   frame contenido: {marco.url[:90]}")

        info = marco.evaluate(JS_PAGINACION)
        print(f"   paginación: {info['pagina']} de {info['totalPaginas']}")
        print(f"   selects: {info['sels']}")

        tabla = marco.evaluate(JS_TABLA)
        if not tabla:
            print("[FALLO] no encontré la tabla")
            nav.close()
            return 1

        print(f"   columnas: {tabla['heads']}")
        print(f"   filas visibles: {len(tabla['filas'])}")
        for fila in tabla["filas"][:3]:
            print(f"     {fila}")

        # El paginador permite escribir el número de página en #pag
        def ir_a_pagina(n: int) -> bool:
            campo = marco.locator("#pag")
            if not campo.count():
                return False
            campo.fill(str(n))
            campo.press("Enter")
            marco.wait_for_timeout(3000)
            return True

        filas: list[list[str]] = list(tabla["filas"])
        vistos = {f[1] for f in filas if len(f) > 1 and f[1]}

        for n in range(2, 12):
            if not ir_a_pagina(n):
                break
            nueva = marco.evaluate(JS_TABLA)
            pagina = nueva["filas"] if nueva else []
            nuevos = [f for f in pagina if len(f) > 1 and f[1] not in vistos]
            if not nuevos:
                print(f"   página {n}: sin registros nuevos, fin")
                break
            for f in nuevos:
                vistos.add(f[1])
            filas.extend(nuevos)
            print(f"   página {n}: +{len(nuevos)} (total {len(filas)})")

        print(f"   filas totales: {len(filas)}")

        print(f"\n3. Exportando {len(filas)} filas a Excel")
        heads = tabla["heads"] or ["Datos"]
        utiles = [
            i for i, h in enumerate(heads)
            if h.strip() and h.strip().lower() != "acciones"
        ]
        heads_util = [heads[i] for i in utiles]

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Despachados"
        hoja.append(heads_util)
        for celda in hoja[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F4E78")

        exportadas = 0
        for fila in filas:
            valores = [fila[i] if i < len(fila) else "" for i in utiles]
            if any(v.strip() for v in valores):
                hoja.append(valores)
                exportadas += 1

        from openpyxl.utils import get_column_letter

        anchos = [14, 14, 20, 28, 28, 28, 20, 45, 14, 16]
        for i in range(1, len(heads_util) + 1):
            ancho = anchos[i - 1] if i - 1 < len(anchos) else 20
            hoja.column_dimensions[get_column_letter(i)].width = ancho
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(heads_util))}{hoja.max_row}"

        ruta = REPORTES / f"documentos_despachados_{marca}.xlsx"
        libro.save(ruta)
        print(f"   guardado: {ruta}")
        print(f"   filas exportadas: {exportadas}")

        nav.close()

    print(f"\nTotal exportado: {exportadas} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
