"""Configuración centralizada, leída de variables de entorno y del catálogo."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


@dataclass
class Configuracion:
    gmail_credentials_file: str = "credentials/gmail_oauth_client.json"
    gmail_token_file: str = "credentials/gmail_token.json"
    # Durante las pruebas se lee el buzón personal; el definitivo es la unidad
    # de correspondencia.
    gmail_mailbox: str = "jvergara@camarapereira.org.co"
    gmail_mailbox_produccion: str = "unidadcorrespondencia@camarapereira.org.co"
    gmail_query: str = "is:unread -label:Radicado"
    gmail_label_processed: str = "Radicado"
    gmail_label_review: str = "PQRSF-Revision"
    gmail_label_failed: str = "PQRSF-Fallido"
    # Etiqueta de la fase 1: marca correos ya leídos y clasificados, sin radicar
    gmail_label_leido: str = "PQRSF-Leido"

    sgd_base_url: str = "https://docxflow.camarapereira.org.co"
    sgd_token: str = ""
    # DocxFlow no tiene API: se entra con usuario y contraseña por navegador.
    docxflow_user: str = ""
    docxflow_password: str = ""
    sgd_timeout: int = 20
    # Mientras sea True, NUNCA se escribe en DocxFlow: se usa el mock local.
    # Es la protección contra crear radicados reales durante las pruebas.
    sgd_modo_prueba: bool = True
    sgd_mock_url: str = "http://localhost:8080"

    umbral_confianza: float = 0.75
    areas_config_file: str = "config/areas.yaml"

    llm_provider: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    state_db_path: str = "var/state.db"
    report_output_dir: str = "var/reportes"
    report_recipients: list[str] = field(default_factory=list)
    report_hour: str = "18:00"

    @classmethod
    def cargar(cls, env_path: str | Path | None = None) -> "Configuracion":
        ruta = Path(env_path) if env_path else RAIZ_PROYECTO / ".env"
        if ruta.exists():
            load_dotenv(ruta, override=False)

        destinatarios = [
            correo.strip()
            for correo in os.getenv("REPORT_RECIPIENTS", "").split(",")
            if correo.strip()
        ]

        return cls(
            gmail_credentials_file=os.getenv(
                "GMAIL_CREDENTIALS_FILE", "credentials/gmail_oauth_client.json"
            ),
            gmail_token_file=os.getenv(
                "GMAIL_TOKEN_FILE", "credentials/gmail_token.json"
            ),
            gmail_mailbox=os.getenv(
                "GMAIL_MAILBOX", "jvergara@camarapereira.org.co"
            ),
            gmail_mailbox_produccion=os.getenv(
                "GMAIL_MAILBOX_PRODUCCION", "unidadcorrespondencia@camarapereira.org.co"
            ),
            gmail_query=os.getenv("GMAIL_QUERY", "is:unread -label:Radicado"),
            gmail_label_processed=os.getenv("GMAIL_LABEL_PROCESSED", "Radicado"),
            gmail_label_review=os.getenv("GMAIL_LABEL_REVIEW", "PQRSF-Revision"),
            gmail_label_failed=os.getenv("GMAIL_LABEL_FAILED", "PQRSF-Fallido"),
            gmail_label_leido=os.getenv("GMAIL_LABEL_LEIDO", "PQRSF-Leido"),
            sgd_base_url=os.getenv(
                "SGD_BASE_URL", "https://docxflow.camarapereira.org.co"
            ),
            sgd_token=os.getenv("SGD_TOKEN", ""),
            docxflow_user=os.getenv("DOCXFLOW_USER", ""),
            docxflow_password=os.getenv("DOCXFLOW_PASSWORD", ""),
            sgd_timeout=int(os.getenv("SGD_TIMEOUT", "20")),
            sgd_modo_prueba=os.getenv("SGD_MODO_PRUEBA", "true").lower()
            in ("1", "true", "si", "sí", "yes"),
            sgd_mock_url=os.getenv("SGD_MOCK_URL", "http://localhost:8080"),
            umbral_confianza=float(os.getenv("CLASSIFIER_CONFIDENCE_THRESHOLD", "0.75")),
            areas_config_file=os.getenv("AREAS_CONFIG_FILE", "config/areas.yaml"),
            llm_provider=os.getenv("LLM_PROVIDER", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            state_db_path=os.getenv("STATE_DB_PATH", "var/state.db"),
            report_output_dir=os.getenv("REPORT_OUTPUT_DIR", "var/reportes"),
            report_recipients=destinatarios,
            report_hour=os.getenv("REPORT_HOUR", "18:00"),
        )

    def ruta(self, relativa: str) -> Path:
        """Resuelve una ruta relativa contra la raíz del proyecto."""
        camino = Path(relativa)
        return camino if camino.is_absolute() else RAIZ_PROYECTO / camino

    @property
    def url_sgd_efectiva(self) -> str:
        """URL que se debe usar de verdad.

        Con SGD_MODO_PRUEBA=true siempre devuelve el mock, aunque
        SGD_BASE_URL apunte a DocxFlow. Evita radicados reales por accidente.
        """
        return self.sgd_mock_url if self.sgd_modo_prueba else self.sgd_base_url


def cargar_catalogo_areas(ruta: str | Path) -> dict:
    with open(ruta, encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)
