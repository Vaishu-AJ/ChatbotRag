"""Split extracted document text into overlapping chunks with source metadata."""

import hashlib


def chunk_pages(
    pages: list[dict[str, object]], chunk_size: int = 1000, overlap: int = 150
) -> list[dict[str, object]]:
    """Split each extracted text block into character-based chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    chunks: list[dict[str, object]] = []
    step = chunk_size - overlap
    for page in pages:
        text = str(page["text"])
        start = 0
        while start < len(text):
            chunk_text = text[start : start + chunk_size].strip()
            if chunk_text:
                source = str(page["source"])
                location = str(page.get("location", page.get("page", "")))
                digest = hashlib.sha256(
                    f"{source}|{location}|{start}|{chunk_text}".encode()
                ).hexdigest()
                chunks.append(
                    {
                        "id": digest,
                        "text": chunk_text,
                        **{key: value for key, value in page.items() if key != "text"},
                    }
                )
            start += step
    return chunks
