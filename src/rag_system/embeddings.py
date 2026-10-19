"""Create document and query embeddings with Ollama or OpenAI."""

from openai import OpenAI

from .config import Settings
from .local_models import ollama_request


def get_embeddings(
    texts: list[str], settings: Settings, client: OpenAI | None = None
) -> list[list[float]]:
    """Embed texts in batches and preserve their input order."""
    if not texts:
        return []

    embeddings: list[list[float]] = []
    batch_size = 100
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        if settings.provider == "ollama":
            response = ollama_request(
                settings.ollama_base_url,
                "/api/embed",
                {"model": settings.embedding_model, "input": batch},
            )
            embeddings.extend(response["embeddings"])
        else:
            if client is None:
                raise RuntimeError("OpenAI provider selected, but no API client is configured.")
            response = client.embeddings.create(model=settings.embedding_model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            embeddings.extend(item.embedding for item in ordered)
    return embeddings
