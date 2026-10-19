"""Persist and query chunk embeddings with Chroma."""

from pathlib import Path
import re

import chromadb

from .config import Settings


def get_collection(directory: Path, name: str = "pdf_documents"):
    """Open or create a persistent Chroma collection."""
    directory.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(directory))
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def get_provider_collection(settings: Settings):
    """Use a separate collection for each provider/model embedding dimension."""
    name_part = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{settings.provider}_{settings.embedding_model}")
    return get_collection(settings.vector_store_directory, f"pdf_{name_part}"[:63])


def store_chunks(collection, chunks: list[dict[str, object]], embeddings: list[list[float]]) -> None:
    """Insert or update chunks and their metadata without clearing existing data."""
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have exactly one embedding")
    if not chunks:
        return

    collection.upsert(
        ids=[str(chunk["id"]) for chunk in chunks],
        documents=[str(chunk["text"]) for chunk in chunks],
        embeddings=embeddings,
        metadatas=[{"source": str(chunk["source"]), "page": int(chunk["page"])} for chunk in chunks],
    )
