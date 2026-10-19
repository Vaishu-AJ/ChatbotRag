"""Coordinate PDF indexing and question answering."""

from openai import OpenAI
from collections.abc import Iterator

from .chunking import chunk_pages
from .config import Settings
from .document_loader import load_pdfs
from .embeddings import get_embeddings
from .generator import generate_answer, stream_answer
from .retriever import retrieve
from .vector_store import get_provider_collection, store_chunks


def index_pdfs(settings: Settings, client: OpenAI | None = None) -> int:
    """Load PDFs, chunk their pages, embed chunks, and store them in Chroma."""
    pages = load_pdfs(settings.pdf_directory)
    chunks = chunk_pages(pages)
    if not chunks:
        raise ValueError("No text could be extracted from the PDFs")
    embeddings = get_embeddings([str(chunk["text"]) for chunk in chunks], settings, client)
    collection = get_provider_collection(settings)
    store_chunks(collection, chunks, embeddings)
    return len(chunks)


def ask(
    question: str,
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Retrieve relevant context and generate an answer for a question."""
    if not question.strip():
        raise ValueError("Question cannot be empty")
    collection = get_provider_collection(settings)
    if collection.count() == 0:
        raise RuntimeError("The vector store is empty. Run the index command first.")
    question_embedding = get_embeddings([question], settings, client)[0]
    matches = retrieve(collection, question_embedding)
    return generate_answer(question, matches, settings, client, history)


def ask_stream(
    question: str,
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """Retrieve relevant PDF passages, then stream the generated answer."""
    if not question.strip():
        raise ValueError("Question cannot be empty")
    collection = get_provider_collection(settings)
    if collection.count() == 0:
        raise RuntimeError("The vector store is empty. Add a PDF and wait for indexing to finish.")
    question_embedding = get_embeddings([question], settings, client)[0]
    matches = retrieve(collection, question_embedding)
    return stream_answer(question, matches, settings, client, history)
