# RAG System

Python retrieval-augmented generation (RAG) app for chatting with PDF documents. The flow is:

1. Load PDF files from `data/documents/`.
2. Split extracted text into chunks.
3. Create embeddings locally with Ollama by default (OpenAI API is optional).
4. Store and retrieve chunks using a local Chroma vector store.
5. Send the question and retrieved context to the selected chat model to draft an answer.

The chat also supports an optional OKF (Open Knowledge Format) bundle. A strong exact match against a current Markdown concept routes directly to that curated concept; otherwise the app falls back to the existing vector RAG path. OKF concepts are not generated from uploads automatically: add and review them in `data/okf/` when you have stable facts that should be answered deterministically. The reader recognizes OKF `type`, `title`, `description`, `tags`, `aliases`, `sources`, `generated`, `verified`, `status`, `stale_after`, and optional `database` frontmatter. Draft, deprecated, and stale concepts are not used for answers.

For live PostgreSQL answers, set `DATABASE_URL` in `.env` and add `nl_to_sql: true` to a reviewed database-backed OKF concept. The planner reads the public schema, asks the configured model for a structured table/column/filter plan, validates every identifier, and compiles its own parameterized `SELECT`; it never executes SQL written by the model. Queries run in a read-only transaction, join crew-related tables only through `crew_code`, and return at most 50 rows. The current crew planner can query all public tables, including bank and payroll tables. Use a PostgreSQL role with `SELECT` permissions only. See `src/rag_system/text_to_sql.py`, `data/okf/crew-certificates.md`, and `data/okf/index.md`. The connection URL must use standard form `postgresql://USER:PASSWORD@HOST:PORT/DATABASE`; percent-encode reserved characters in credentials.

The project loads text from PDFs, indexes it locally, retrieves relevant passages, and answers questions in a chatbot. Ollama runs locally without per-token API charges; the optional OpenAI API is billed separately.

## Setup

1. Create and activate a virtual environment.
2. Install the project and local media processors: `python -m pip install -e ".[dev,media]"`
3. Install [Ollama](https://ollama.com/download), start it, then download the models: `ollama pull llama3.2:3b`, `ollama pull nomic-embed-text`, and `ollama pull gemma3:4b`.
4. Place supported files in `data/documents/` (or set `PDF_DIRECTORY` in `.env`). Accepted types include PDFs, common images, audio, and video formats; see `src/rag_system/multimodal.py` for the extensions.
5. In one terminal, start the Python API: `uvicorn rag_system.api:app --reload --reload-dir src` (watch the source tree only; do not watch the virtual environment).
6. In a second terminal, enter the React frontend folder and start Vite: `cd frontend` then `npm install` and `npm run dev`.
7. Open the local URL printed by Vite (usually `http://localhost:5173`). Upload files in the sidebar; the API indexes them automatically. Ask questions, start chats, or reopen and delete saved conversations.

To run the built React app from one server instead, run `cd frontend && npm run build`, then start the API with `uvicorn rag_system.api:app --reload --reload-dir src` and open `http://127.0.0.1:8000`.

Answers stream into the React chat as the model generates them. Images and PDF-embedded images are described by the configured Ollama vision model; audio is transcribed locally with faster-whisper; videos are sampled every 30 seconds for visual descriptions and their audio is transcribed when present. Ollama must be running with the vision model installed for image or video-frame indexing. Audio/video processing needs the `media` extra; faster-whisper downloads its local speech model on first use. Chat history is saved locally in `data/chat_history.json`. Streamlit remains available as a legacy PDF-only UI with `streamlit run app.py`.

## Project layout

```text
RAG System/
├── data/
│   ├── documents/       # Source PDFs (kept out of Git)
│   ├── okf/              # Curated OKF Markdown concepts (tracked in Git)
│   ├── processed/       # Optional extracted/intermediate data
│   └── vector_store/    # Local vector index (created when implemented)
├── src/rag_system/
│   ├── api.py           # FastAPI backend for the React frontend
│   ├── okf.py            # OKF bundle parser, trust signals, exact-match router
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

Routing examples and their expected database, document, or hybrid route are recorded in
`data/evaluations/routing_cases.json`. Extend this adjudicated smoke set with anonymized
queries when routing behavior changes; it is a regression aid, not a production quality score.
