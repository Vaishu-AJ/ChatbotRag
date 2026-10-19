"""Streamlit chatbot for asking questions about PDF documents."""

import json
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from openai import OpenAI

from .config import PROJECT_ROOT, get_settings
from .local_models import ollama_request
from .pipeline import ask_stream, index_pdfs
from .vector_store import get_provider_collection

HISTORY_FILE = PROJECT_ROOT / "data" / "chat_history.json"


def _load_threads() -> list[dict]:
    try:
        threads = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        for thread in threads:
            thread["title"] = _conversation_title(thread.get("messages", []))
        return threads
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_threads() -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(
            [thread for thread in st.session_state.chat_threads if thread["messages"]],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _new_thread() -> dict:
    thread = {
        "id": uuid.uuid4().hex,
        "title": "New conversation",
        "created": datetime.now().astimezone().isoformat(timespec="minutes"),
        "messages": [],
    }
    st.session_state.chat_threads.insert(0, thread)
    st.session_state.active_thread_id = thread["id"]
    return thread


def _start_new_chat() -> None:
    _new_thread()


def _select_thread(thread_id: str) -> None:
    st.session_state.active_thread_id = thread_id


def _is_follow_up(question: str) -> bool:
    """Only carry prior turns into questions that clearly depend on them."""
    text = question.strip().lower()
    starts_as_follow_up = (
        "and ", "also ", "what about ", "how about ", "why is it", "how does it",
        "what does it", "tell me more", "explain more", "elaborate",
    )
    reference_words = {"it", "its", "they", "them", "this", "that", "these", "those", "he", "she", "her", "his"}
    words = {word.strip(".,?!:;()[]{}\"'") for word in text.split()}
    return text.startswith(starts_as_follow_up) or bool(words & reference_words)


def _greeting_response(question: str) -> str | None:
    """Respond naturally to a standalone greeting without searching PDFs."""
    text = " ".join(question.lower().strip().split()).strip(" .,!?;:")
    greetings = {
        "hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon",
        "good evening", "hi there", "hello there", "hey there", "how are you",
        "how are you doing",
    }
    if text in greetings:
        return "Hi! How can I help you today?"
    return None


def _conversation_title(messages: list[dict]) -> str:
    """Use the first meaningful question as the history label, skipping greetings."""
    for message in messages:
        if message.get("role") != "user":
            continue
        question = str(message.get("content", "")).strip()
        if question and _greeting_response(question) is None:
            return question[:48]
    return "New chat"


def _delete_thread(thread_id: str) -> None:
    """Delete a saved conversation and switch away if it was open."""
    st.session_state.chat_threads = [
        thread for thread in st.session_state.chat_threads if thread["id"] != thread_id
    ]
    if st.session_state.active_thread_id == thread_id:
        if st.session_state.chat_threads:
            st.session_state.active_thread_id = st.session_state.chat_threads[0]["id"]
        else:
            _new_thread()
    _save_threads()


def _save_uploaded_pdfs() -> None:
    settings = get_settings()
    settings.pdf_directory.mkdir(parents=True, exist_ok=True)
    uploaded = st.session_state.get("pdf_upload") or []
    saved = []
    for item in uploaded:
        name = Path(item.name).name
        (settings.pdf_directory / name).write_bytes(item.getvalue())
        saved.append(name)
    if saved:
        st.session_state.upload_notice = f"Added {len(saved)} PDF{'s' if len(saved) != 1 else ''}. Indexing now…"


def _file_manifest(pdf_files: list[Path]) -> list[dict[str, int | str]]:
    manifest = []
    for path in pdf_files:
        stat = path.stat()
        manifest.append({"name": path.name, "size": stat.st_size, "modified": stat.st_mtime_ns})
    return manifest


def _manifest_path(settings, collection) -> Path:
    folder = settings.vector_store_directory.parent / "index_manifests"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{collection.name}.json"


def _local_provider_ready(settings) -> bool:
    if settings.provider != "ollama":
        return bool(settings.openai_api_key)
    try:
        response = ollama_request(settings.ollama_base_url, "/api/tags")
        installed = {model.get("name", "") for model in response.get("models", [])}
        installed.update(name.removesuffix(":latest") for name in tuple(installed))
        return settings.chat_model in installed and settings.embedding_model in installed
    except RuntimeError:
        return False


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
        :root { --ink:#17231f; --muted:#728078; --green:#2b7658; --line:#e6ebe6; }
        html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
        .stApp { background:#f7f9f6; color:var(--ink); }
        [data-testid="stHeader"] { background:transparent; }
        [data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--line); }
        [data-testid="stSidebar"] > div:first-child { padding-top:1.2rem; }
        .brand { display:flex; align-items:center; gap:11px; margin:0 0 25px 2px; }
        .brand-mark { width:38px; height:38px; border-radius:13px; display:grid; place-items:center; color:#fff; background:#286c50; font-size:20px; box-shadow:0 5px 14px #286c5030; }
        .brand-name { font:800 19px 'Manrope',sans-serif; letter-spacing:-.7px; color:#1b3025; }
        .brand-name span { color:#458365; }
        .section-label { color:#829087; text-transform:uppercase; letter-spacing:1px; font-size:10px; font-weight:700; margin:22px 0 9px; }
        .hero { padding:28px 0 22px; border-bottom:1px solid var(--line); margin-bottom:22px; }
        .hero-kicker { display:inline-flex; color:#397457; background:#eaf3e9; padding:6px 11px; border-radius:999px; font-size:12px; font-weight:700; }
        .hero h1 { font:800 clamp(29px,4vw,40px) 'Manrope',sans-serif; letter-spacing:-1.6px; margin:15px 0 6px; color:#17251e; }
        .hero p { color:#748078; font-size:14px; margin:0; }
        .welcome-card { border:1px solid #e2e9e1; border-radius:18px; padding:22px 24px; background:linear-gradient(135deg,#fff 0%,#f3f8ef 100%); margin:10px 0 16px; }
        .welcome-card h3 { margin:0 0 6px; font:700 18px 'Manrope',sans-serif; color:#20392b; }
        .welcome-card p { color:#718078; margin:0; font-size:14px; }
        .stButton button { border-radius:11px; border-color:#dce5dc; color:#345f48; font-weight:600; text-align:left; }
        .stButton button[kind="primary"] { background:#286c50; border-color:#286c50; color:#fff; text-align:center; }
        [data-testid="stChatMessage"] { border:1px solid #e5eae4; border-radius:16px; padding:13px 16px; background:white; }
        [data-testid="stChatInput"] { border-color:#dce5dc; border-radius:16px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="PaperPilot · PDF Chat", page_icon="🌿", layout="wide")
    _apply_styles()
    settings = get_settings()

    if "chat_threads" not in st.session_state:
        st.session_state.chat_threads = _load_threads()
    else:
        # Refresh labels even in an existing Streamlit session after code changes.
        for saved_thread in st.session_state.chat_threads:
            saved_thread["title"] = _conversation_title(saved_thread.get("messages", []))
    if "active_thread_id" not in st.session_state or not any(
        item["id"] == st.session_state.active_thread_id for item in st.session_state.chat_threads
    ):
        _new_thread()
    thread = next(item for item in st.session_state.chat_threads if item["id"] == st.session_state.active_thread_id)

    st.sidebar.markdown(
        '<div class="brand"><div class="brand-mark">✳</div><div class="brand-name">Ask<span>Me</span></div></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.button("＋  New chat", type="primary", use_container_width=True, on_click=_start_new_chat)
    st.sidebar.markdown('<div class="section-label">Chat history</div>', unsafe_allow_html=True)
    old_threads = [item for item in st.session_state.chat_threads if item["messages"]]
    if not old_threads:
        st.sidebar.caption("Your conversations will appear here.")
    else:
        for item in old_threads[:30]:
            title = item["title"][:34] + ("…" if len(item["title"]) > 34 else "")
            history_col, delete_col = st.sidebar.columns([0.82, 0.18], gap="small")
            history_col.button(
                f"▢  {title}", key=f"thread_{item['id']}", use_container_width=True,
                on_click=_select_thread, args=(item["id"],),
            )
            delete_col.button(
                "×", key=f"delete_{item['id']}", help="Delete this chat",
                use_container_width=True, on_click=_delete_thread, args=(item["id"],),
            )
    st.sidebar.markdown('<div class="section-label">Your PDFs</div>', unsafe_allow_html=True)
    st.sidebar.file_uploader(
        "Upload PDF files", type=["pdf"], accept_multiple_files=True, key="pdf_upload",
        on_change=_save_uploaded_pdfs, help="New PDFs are indexed automatically after upload.",
    )

    if st.session_state.get("upload_notice"):
        st.sidebar.success(st.session_state.pop("upload_notice"))

    pdfs = sorted(settings.pdf_directory.glob("*.pdf")) if settings.pdf_directory.exists() else []
    collection = get_provider_collection(settings)
    ready = _local_provider_ready(settings)
    if pdfs and ready:
        signature = _file_manifest(pdfs)
        manifest_path = _manifest_path(settings, collection)
        try:
            previous_signature = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            previous_signature = None
        if signature != previous_signature:
            try:
                with st.spinner("Preparing your PDFs for chat…"):
                    index_pdfs(settings, OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai" else None)
                manifest_path.write_text(json.dumps(signature, indent=2), encoding="utf-8")
                st.toast("PDFs are ready to chat with.", icon="✅")
            except Exception as error:
                st.error(f"I couldn't index the PDFs: {error}")
    elif pdfs and not ready:
        st.sidebar.info("The assistant is unavailable. Check that its local service is running and models are installed.")

    st.markdown(
        '<div class="hero"><span class="hero-kicker">✦ &nbsp; YOUR DOCUMENT ASSISTANT</span>'
        '<h1>What would you like to know?</h1><p>Ask a question and get an answer grounded in your PDFs.</p></div>',
        unsafe_allow_html=True,
    )
    if not pdfs:
        st.markdown(
            '<div class="welcome-card"><h3>Start with a PDF</h3>'
            '<p>Upload one or more PDFs from the sidebar. They will be indexed automatically and ready for questions.</p></div>',
            unsafe_allow_html=True,
        )
    elif collection.count() == 0:
        st.markdown(
            '<div class="welcome-card"><h3>Getting your documents ready</h3>'
            '<p>Indexing starts automatically when the assistant is available. You can leave this page open.</p></div>',
            unsafe_allow_html=True,
        )

    for message in thread["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    can_chat = collection.count() > 0 and ready
    prompt = st.chat_input("Ask something about your PDFs…", disabled=not can_chat)
    if prompt:
        history = thread["messages"][-8:] if _is_follow_up(prompt) else []
        thread["messages"].append({"role": "user", "content": prompt})
        thread["title"] = _conversation_title(thread["messages"])
        _save_threads()
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            try:
                answer = _greeting_response(prompt)
                if answer is not None:
                    st.markdown(answer)
                else:
                    with st.spinner("Searching your PDFs…"):
                        answer_stream = ask_stream(
                            prompt,
                            settings,
                            OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai" else None,
                            history,
                        )
                    answer = st.write_stream(answer_stream)
            except Exception as error:
                answer = f"I couldn't complete that request: {error}"
                st.error(answer)
        thread["messages"].append({"role": "assistant", "content": answer})
        _save_threads()


if __name__ == "__main__":
    main()
