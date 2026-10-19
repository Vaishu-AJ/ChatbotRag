"""Split PDF page text into overlapping chunks while keeping source metadata."""


def chunk_pages(
    pages: list[dict[str, object]], chunk_size: int = 1000, overlap: int = 150
) -> list[dict[str, object]]:
    """Split each page's text into character-based chunks."""
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
                chunks.append(
                    {
                        "id": f"chunk-{len(chunks)}",
                        "text": chunk_text,
                        "source": str(page["source"]),
                        "page": int(page["page"]),
                    }
                )
            start += step
    return chunks
