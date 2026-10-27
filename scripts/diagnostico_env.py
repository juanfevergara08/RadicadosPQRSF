"""Diagnóstico de las credenciales cargadas desde .env.

Nunca muestra la contraseña: solo su forma, para detectar los errores
habituales de configuración.

    python scripts/diagnostico_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from radicados.config import Configuracion  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def describir(nombre: str, valor: str) -> None:
    print(f"\n{nombre}:")
    print(f"  longitud ............ {len(valor)}")
    print(f"  valor ................ {valor!r}" if nombre == "usuario" else "  valor ................ (oculto)")
    if not valor:
        return
    print(f"  espacios al borde .... {'SÍ (error)' if valor != valor.strip() else 'no'}")
    print(f"  contiene '#' ......... {'SÍ (revisa comillas)' if '#' in valor else 'no'}")
    print(f"  contiene '$' ......... {'SÍ (revisa comillas)' if '$' in valor else 'no'}")
    print(f"  contiene comillas .... {'SÍ (revisa comillas)' if ('\"' in valor or "'" in valor) else 'no'}")
    print(f"  solo caracteres ASCII  {'sí' if valor.isascii() else 'NO (acentos o símbolos)'}")
    print(f"  primer carácter ...... {valor[0]!r}")
    print(f"  último carácter ...... {valor[-1]!r}")


def main() -> int:
    ruta_env = RAIZ / ".env"
    print(f"Archivo .env: {ruta_env} ({'existe' if ruta_env.exists() else 'NO EXISTE'})")

    config = Configuracion.cargar()
    describir("usuario", config.docxflow_user)
    describir("contraseña", config.docxflow_password)

    print(f"\nURL del SGD ........... {config.sgd_base_url}")
    print(f"Buzón Gmail ........... {config.gmail_mailbox}")
    print(f"Modo prueba ........... {config.sgd_modo_prueba}")

    problemas = []
    if not config.docxflow_user:
        problemas.append("DOCXFLOW_USER está vacío")
    if not config.docxflow_password:
        problemas.append("DOCXFLOW_PASSWORD está vacío")
    if config.docxflow_password != config.docxflow_password.strip():
        problemas.append("la contraseña tiene espacios al inicio o al final")
    if "#" in config.docxflow_password:
        problemas.append("la contraseña contiene '#' sin comillas: puede estar cortada")

    if problemas:
        print("\n[PROBLEMAS]")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    print("\n[OK] Las credenciales se cargan completas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
