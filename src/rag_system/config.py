"""Load application settings from environment variables and a local .env file."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Configuration used by the RAG pipeline."""

    provider: str
    openai_api_key: str | None
    chat_model: str
    embedding_model: str
    vision_model: str
    ollama_base_url: str
    pdf_directory: Path
    vector_store_directory: Path
    okf_directory: Path
    database_url: str | None
    database_media_base_url: str
    database_media_token: str | None


def get_settings() -> Settings:
    """Read application and provider settings from environment variables."""
    provider = os.getenv("RAG_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        raise ValueError("RAG_PROVIDER must be either 'ollama' or 'openai'")
    api_key = os.getenv("OPENAI_API_KEY", "").strip() or None

    def project_path(name: str, default: str) -> Path:
        value = Path(os.getenv(name, default)).expanduser()
        return value if value.is_absolute() else PROJECT_ROOT / value

    return Settings(
        provider=provider,
        openai_api_key=api_key,
        chat_model=(
            os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:3b")
            if provider == "ollama"
            else os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        ),
        embedding_model=(
            os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
            if provider == "ollama"
            else os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        ),
        vision_model=os.getenv("OLLAMA_VISION_MODEL", "gemma3:4b"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        pdf_directory=project_path("PDF_DIRECTORY", "data/documents"),
        vector_store_directory=project_path("VECTOR_STORE_DIRECTORY", "data/vector_store"),
        okf_directory=project_path("OKF_DIRECTORY", "data/okf"),
        database_url=os.getenv("DATABASE_URL", "").strip() or None,
        database_media_base_url=os.getenv("DATABASE_MEDIA_BASE_URL", "").strip().rstrip("/"),
        database_media_token=os.getenv("DATABASE_MEDIA_TOKEN", "").strip() or None,
    )
