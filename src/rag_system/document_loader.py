"""Extract text and page metadata from PDF files."""

from pathlib import Path

from pypdf import PdfReader


def load_pdf(pdf_path: Path) -> list[dict[str, object]]:
    """Return non-empty pages from one PDF, retaining source and page number."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {pdf_path}")

    pages: list[dict[str, object]] = []
    reader = PdfReader(str(pdf_path))
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            pages.append({"source": str(pdf_path.resolve()), "page": page_number, "text": page_text})
    return pages


def load_pdfs(directory: Path) -> list[dict[str, object]]:
    """Load all PDF files in a directory (non-recursively)."""
    if not directory.is_dir():
        raise NotADirectoryError(f"PDF directory not found: {directory}")
    pdf_files = sorted(directory.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {directory}")
    return [page for pdf_path in pdf_files for page in load_pdf(pdf_path)]
