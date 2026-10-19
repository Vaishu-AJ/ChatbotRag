"""Command-line interface for indexing PDFs and asking questions."""

import argparse

from openai import OpenAI

from .config import get_settings
from .pipeline import ask, index_pdfs


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask questions about your PDF documents.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("index", help="Index PDFs from the configured directory")
    ask_parser = subparsers.add_parser("ask", help="Ask a question about indexed PDFs")
    ask_parser.add_argument("question", help="Question to answer")
    args = parser.parse_args()

    settings = get_settings()
    if settings.provider == "openai" and not settings.openai_api_key:
        raise RuntimeError("Set OPENAI_API_KEY in .env or choose RAG_PROVIDER=ollama.")
    client = OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai" else None
    if args.command == "index":
        print(f"Indexed {index_pdfs(settings, client)} chunks.")
    else:
        print(ask(args.question, settings, client))


if __name__ == "__main__":
    main()
