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
5. In one terminal, start the Python API: `uvicorn rag_system.api:app --reload`.
6. In a second terminal, enter the React frontend folder and start Vite: `cd frontend` then `npm install` and `npm run dev`.
7. Open the local URL printed by Vite (usually `http://localhost:5173`). Upload PDFs in the sidebar; the API indexes them automatically. Ask questions, start chats, or reopen and delete saved conversations.

To run the built React app from one server instead, run `cd frontend && npm run build`, then start the API with `uvicorn rag_system.api:app --reload` and open `http://127.0.0.1:8000`.

Answers stream into the React chat as the model generates them. Chat history is saved locally in `data/chat_history.json`. Streamlit remains available as a legacy UI with `streamlit run app.py`.

## Project layout

```text
RAG System/
├── data/
│   ├── documents/       # Source PDFs (kept out of Git)
│   ├── processed/       # Optional extracted/intermediate data
│   └── vector_store/    # Local vector index (created when implemented)
├── src/rag_system/
│   ├── api.py           # FastAPI backend for the React frontend
│   ├── config.py        # Environment and application settings
│   ├── document_loader.py
│   ├── chunking.py
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── retriever.py
│   ├── generator.py
│   ├── pipeline.py
│   ├── cli.py
│   └── web_app.py       # Legacy Streamlit PDF chatbot
├── frontend/            # React + Vite user interface
├── app.py               # Legacy Streamlit entry point
└── tests/               # Future unit and integration tests
```

## Command-line interface

The CLI remains available after installation: `rag-system index` and `rag-system ask "your question"`.
