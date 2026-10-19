# RAG System

Python retrieval-augmented generation (RAG) app for chatting with PDF documents. The flow is:

1. Load PDF files from `data/documents/`.
2. Split extracted text into chunks.
3. Create embeddings locally with Ollama by default (OpenAI API is optional).
4. Store and retrieve chunks using a local Chroma vector store.
5. Send the question and retrieved context to the selected chat model to draft an answer.

The project loads text from PDFs, indexes it locally, retrieves relevant passages, and answers questions in a chatbot. Ollama runs locally without per-token API charges; the optional OpenAI API is billed separately.

## Setup

1. Create and activate a virtual environment.
2. Install the project with development tools: `python -m pip install -e ".[dev]"`
3. Install [Ollama](https://ollama.com/download), start it, then download the default models: `ollama pull llama3.2:3b` and `ollama pull nomic-embed-text`.
4. Place PDF files in `data/documents/` (or set `PDF_DIRECTORY` in `.env`).
5. Start the chatbot: `streamlit run app.py`.
6. Upload PDFs in the sidebar; the app indexes them automatically. Ask questions in the chat box, start a new chat, or reopen a previous conversation from the sidebar.

Answers stream into the chat as the local model generates them. Chat history is saved locally in `data/chat_history.json`.

## Project layout

```text
RAG System/
├── data/
│   ├── documents/       # Source PDFs (kept out of Git)
│   ├── processed/       # Optional extracted/intermediate data
│   └── vector_store/    # Local vector index (created when implemented)
├── src/rag_system/
│   ├── config.py        # Environment and application settings
│   ├── document_loader.py
│   ├── chunking.py
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── retriever.py
│   ├── generator.py
│   ├── pipeline.py
│   ├── cli.py
│   └── web_app.py       # Streamlit PDF chatbot
├── app.py               # Web app entry point
└── tests/               # Future unit and integration tests
```

## Command-line interface

The CLI remains available after installation: `rag-system index` and `rag-system ask "your question"`.
