"""Sesión de navegador contra DocxFlow.

Pieza compartida entre el reconocimiento y la radicación futura. Encapsula lo
que aprendimos del sistema real:

  - El shell se sirve en /login incluso después de autenticar.
  - El contenido vive en iframes: hay que entrar al frame, no a la página.
  - DocxFlow mantiene una sesión por dispositivo. Volver a iniciar sesión en
    cada corrida provoca rechazos intermitentes.
  - Por eso se guarda el estado del contexto (`sesion.json`) y se reutiliza.

Nada de esto radica documentos: solo abre y autentica.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import Configuracion

# Elementos que solo existen con la sesión iniciada
SELECTOR_AUTENTICADO = "a[href='/logout'], #opcRol"


class ErrorLogin(RuntimeError):
    """No se pudo establecer la sesión."""


def _autenticado(pagina) -> bool:
    try:
        return pagina.locator(SELECTOR_AUTENTICADO).count() > 0
    except Exception:  # noqa: BLE001
        return False


def _texto_visible(pagina) -> str:
    """Fragmento del cuerpo para diagnosticar un login fallido."""
    try:
        return " ".join(pagina.inner_text("body").split())[:300]
    except Exception:  # noqa: BLE001
        return "(sin texto)"


def iniciar_sesion(pagina, config: Configuracion, intentos: int = 2) -> None:
    """Garantiza una sesión autenticada en la página dada."""
    ultimo_texto = ""

    for intento in range(1, intentos + 1):
        pagina.goto(config.sgd_base_url, wait_until="networkidle", timeout=60000)
        pagina.wait_for_timeout(1200)

        if _autenticado(pagina):
            return

        # El formulario puede tardar en aparecer
        try:
            pagina.wait_for_selector("#username", timeout=15000)
        except Exception as error:  # noqa: BLE001
            ultimo_texto = _texto_visible(pagina)
            if intento == intentos:
                raise ErrorLogin(
                    f"No apareció el formulario de login. Texto en pantalla: "
                    f"{ultimo_texto}"
                ) from error
            continue

        pagina.locator("#username").fill(config.docxflow_user)
        pagina.locator("#password").fill(config.docxflow_password)
        pagina.locator("#password").press("Enter")

        try:
            pagina.wait_for_selector(SELECTOR_AUTENTICADO, timeout=25000)
            pagina.wait_for_load_state("networkidle", timeout=20000)
            return
        except Exception:  # noqa: BLE001
            ultimo_texto = _texto_visible(pagina)
            pagina.wait_for_timeout(2000)

    raise ErrorLogin(
        "No se pudo iniciar sesión tras "
        f"{intentos} intentos. Texto en pantalla: {ultimo_texto}"
    )


def abrir_contexto(navegador, ruta_sesion: Optional[Path] = None):
    """Crea el contexto reutilizando la sesión guardada si existe."""
    argumentos = {"viewport": {"width": 1400, "height": 900}}
    if ruta_sesion and ruta_sesion.exists():
        argumentos["storage_state"] = str(ruta_sesion)
    return navegador.new_context(**argumentos)


def guardar_sesion(contexto, ruta_sesion: Path) -> None:
    ruta_sesion.parent.mkdir(parents=True, exist_ok=True)
    contexto.storage_state(path=str(ruta_sesion))


def frame_contenido(pagina):
    """Devuelve el frame que contiene la aplicación (no el del visor)."""
    candidatos = [
        frame for frame in pagina.frames if frame.url and "/login" not in frame.url
    ]
    if candidatos:
        return candidatos[-1]
    return pagina.main_frame
