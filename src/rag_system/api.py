"""FastAPI backend used by the React PDF chat interface."""

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from .config import PROJECT_ROOT, get_settings
from .local_models import ollama_request
from .pipeline import ask_stream, index_pdfs
from .vector_store import get_provider_collection

app = FastAPI(title="PaperPilot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY_FILE = PROJECT_ROOT / "data" / "chat_history.json"
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-indexer")
INDEX_LOCK = threading.Lock()
INDEX_STATE: dict[str, str | int] = {"status": "idle", "message": "", "chunks": 0}


class ChatRequest(BaseModel):
    question: str


def _load_chats() -> list[dict]:
    try:
        chats = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    for chat in chats:
        chat["title"] = _chat_title(chat.get("messages", []))
    return chats


def _save_chats(chats: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(chats, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_greeting(text: str) -> bool:
    normalized = " ".join(text.lower().strip().split()).strip(" .,!?;:")
    return normalized in {
        "hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon",
        "good evening", "hi there", "hello there", "hey there", "how are you",
        "how are you doing",
    }


def _chat_title(messages: list[dict]) -> str:
    for message in messages:
        content = str(message.get("content", "")).strip()
        if message.get("role") == "user" and content and not _is_greeting(content):
            return content[:48]
    return "New chat"


def _is_follow_up(question: str) -> bool:
    normalized = question.strip().lower()
    starts_as_follow_up = (
        "and ", "also ", "what about ", "how about ", "why is it", "how does it",
        "what does it", "tell me more", "explain more", "elaborate",
    )
    references = {"it", "its", "they", "them", "this", "that", "these", "those", "he", "she", "her", "his"}
    words = {word.strip(".,?!:;()[]{}\"'") for word in normalized.split()}
    return normalized.startswith(starts_as_follow_up) or bool(words & references)


def _get_chat(chats: list[dict], chat_id: str) -> dict:
    chat = next((entry for entry in chats if entry.get("id") == chat_id), None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def _provider_ready(settings) -> bool:
    if settings.provider == "openai":
        return bool(settings.openai_api_key)
    try:
        response = ollama_request(settings.ollama_base_url, "/api/tags")
        installed = {model.get("name", "") for model in response.get("models", [])}
        installed.update(name.removesuffix(":latest") for name in tuple(installed))
        return settings.chat_model in installed and settings.embedding_model in installed
    except RuntimeError:
        return False


def _manifest(pdf_files: list[Path]) -> list[dict[str, int | str]]:
    return [
        {"name": path.name, "size": path.stat().st_size, "modified": path.stat().st_mtime_ns}
        for path in pdf_files
    ]


def _manifest_path(settings, collection) -> Path:
    directory = settings.vector_store_directory.parent / "index_manifests"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{collection.name}.json"


def _index_documents() -> None:
    if not INDEX_LOCK.acquire(blocking=False):
        return
    settings = get_settings()
    try:
        files = sorted(settings.pdf_directory.glob("*.pdf"))
        if not files:
            INDEX_STATE.update(status="idle", message="", chunks=0)
            return
        INDEX_STATE.update(status="indexing", message="Preparing PDFs for chat…")
        client = OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai" else None
        count = index_pdfs(settings, client)
        collection = get_provider_collection(settings)
        _manifest_path(settings, collection).write_text(
            json.dumps(_manifest(files), indent=2), encoding="utf-8"
        )
        INDEX_STATE.update(status="ready", message="PDFs are ready to chat with.", chunks=count)
    except Exception as error:
        INDEX_STATE.update(status="error", message=str(error))
    finally:
        INDEX_LOCK.release()


def _needs_indexing(settings) -> bool:
    files = sorted(settings.pdf_directory.glob("*.pdf"))
    if not files:
        return False
    collection = get_provider_collection(settings)
    try:
        saved = json.loads(_manifest_path(settings, collection).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        saved = None
    return saved != _manifest(files)


@app.on_event("startup")
def _startup_index() -> None:
    settings = get_settings()
    if _provider_ready(settings) and _needs_indexing(settings):
        INDEX_STATE.update(status="queued", message="Preparing PDFs for chat…")
        EXECUTOR.submit(_index_documents)


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    settings = get_settings()
    pdfs = sorted(settings.pdf_directory.glob("*.pdf")) if settings.pdf_directory.exists() else []
    collection = get_provider_collection(settings)
    return {
        "chats": _load_chats(),
        "documents": [path.name for path in pdfs],
        "provider_ready": _provider_ready(settings),
        "indexed_chunks": collection.count(),
        "index": INDEX_STATE.copy(),
    }


@app.get("/api/chats")
def chats() -> list[dict]:
    return _load_chats()


@app.post("/api/chats", status_code=201)
def create_chat() -> dict:
    chat = {
        "id": uuid.uuid4().hex,
        "title": "New chat",
        "created": datetime.now().astimezone().isoformat(timespec="minutes"),
        "messages": [],
    }
    saved = _load_chats()
    saved.insert(0, chat)
    _save_chats(saved)
    return chat


@app.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str) -> None:
    saved = _load_chats()
    remaining = [chat for chat in saved if chat.get("id") != chat_id]
    if len(remaining) == len(saved):
        raise HTTPException(status_code=404, detail="Chat not found")
    _save_chats(remaining)


@app.post("/api/documents")
async def upload_documents(files: Annotated[list[UploadFile], File()]) -> dict:
    settings = get_settings()
    settings.pdf_directory.mkdir(parents=True, exist_ok=True)
    saved_names = []
    for upload in files:
        name = Path(upload.filename or "document.pdf").name
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{name} is not a PDF")
        content = await upload.read()
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail=f"{name} is not a valid PDF")
        (settings.pdf_directory / name).write_bytes(content)
        saved_names.append(name)
    if saved_names:
        if not _provider_ready(settings):
            raise HTTPException(status_code=503, detail="The selected model service is not available")
        INDEX_STATE.update(status="queued", message="Upload complete. Indexing PDFs…")
        EXECUTOR.submit(_index_documents)
    return {"documents": saved_names, "index": INDEX_STATE.copy()}


@app.get("/api/index")
def index_status() -> dict:
    return INDEX_STATE.copy()


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, request: ChatRequest) -> StreamingResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Enter a question")
    saved = _load_chats()
    chat = _get_chat(saved, chat_id)
    history = chat["messages"][-8:] if _is_follow_up(question) else []
    chat["messages"].append({"role": "user", "content": question})
    chat["title"] = _chat_title(chat["messages"])
    _save_chats(saved)

    def response_stream():
        answer_parts: list[str] = []
        try:
            if _is_greeting(question):
                chunks = iter(("Hi! How can I help you with your PDFs today?",))
            else:
                settings = get_settings()
                client = OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai" else None
                chunks = ask_stream(question, settings, client, history)
            for part in chunks:
                answer_parts.append(part)
                yield part
        except Exception as error:
            answer_parts.append(f"I couldn't complete that request: {error}")
            yield answer_parts[-1]
        finally:
            current = _load_chats()
            current_chat = next((entry for entry in current if entry.get("id") == chat_id), None)
            if current_chat is not None:
                current_chat["messages"].append({"role": "assistant", "content": "".join(answer_parts)})
                _save_chats(current)

    return StreamingResponse(response_stream(), media_type="text/plain; charset=utf-8")


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="react-frontend")
