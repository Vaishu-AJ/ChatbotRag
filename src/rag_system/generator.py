"""Generate answers grounded in retrieved PDF excerpts."""

from collections.abc import Iterator
from pathlib import Path

from openai import OpenAI

from .config import Settings
from .local_models import ollama_request, ollama_stream


def _messages(
    question: str,
    retrieved_chunks: list[dict[str, object]],
    history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    context_parts = []
    for item in retrieved_chunks:
        metadata = item["metadata"]
        context_parts.append(
            f"Source: {Path(str(metadata['source'])).name}\n{item['text']}"
        )
    context = "\n\n---\n\n".join(context_parts)
    messages = [
        {
            "role": "system",
            "content": (
                "Answer the latest user question directly using relevant PDF excerpts. The excerpts "
                "are the factual source: use them when they contain the answer, and do not claim "
                "information is missing when it is present. Conversation history is only for resolving "
                "clear follow-up references; ignore earlier topics when the latest question introduces "
                "a new person, document, or subject. If no relevant excerpt supports an answer, say so "
                "briefly without guessing. If a citation helps, cite only the PDF filename; do not include page numbers."
            ),
        }
    ]
    for turn in (history or [])[-8:]:
        if turn.get("role") in {"user", "assistant"}:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})
    return messages


def generate_answer(
    question: str,
    retrieved_chunks: list[dict[str, object]],
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Return one complete answer for command-line callers."""
    if not retrieved_chunks:
        return "I could not find relevant information in the indexed PDFs."
    messages = _messages(question, retrieved_chunks, history)
    if settings.provider == "ollama":
        response = ollama_request(
            settings.ollama_base_url,
            "/api/chat",
            {
                "model": settings.chat_model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": 256},
            },
        )
        return response.get("message", {}).get("content", "") or "The model returned an empty answer."
    if client is None:
        raise RuntimeError("OpenAI provider selected, but no API client is configured.")
    response = client.chat.completions.create(model=settings.chat_model, messages=messages)
    return response.choices[0].message.content or "The model returned an empty answer."


def stream_answer(
    question: str,
    retrieved_chunks: list[dict[str, object]],
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """Yield answer text as soon as the selected model generates it."""
    if not retrieved_chunks:
        yield "I could not find relevant information in the indexed PDFs."
        return
    messages = _messages(question, retrieved_chunks, history)
    if settings.provider == "ollama":
        yield from ollama_stream(
            settings.ollama_base_url,
            "/api/chat",
            {
                "model": settings.chat_model,
                "messages": messages,
                "stream": True,
                "options": {"num_predict": 256},
            },
        )
        return
    if client is None:
        raise RuntimeError("OpenAI provider selected, but no API client is configured.")
    response = client.chat.completions.create(
        model=settings.chat_model, messages=messages, stream=True
    )
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            yield content
