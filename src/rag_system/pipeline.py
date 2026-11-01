"""Coordinate PDF indexing and question answering."""

import logging
import re
from openai import OpenAI
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from .chunking import chunk_pages
from .config import Settings
from .database import lookup_postgres
from .embeddings import get_embeddings
from .generator import generate_answer, stream_answer
from .multimodal import load_documents
from .media_proxy import register_media_path
from .okf import _tokens, search_bundle
from .retriever import retrieve
from .text_to_sql import lookup_postgres_natural
from .vector_store import get_provider_collection, store_chunks
from .timing import timed_stage

logger = logging.getLogger(__name__)
_DOCUMENT_INTENT = {
    "document", "file", "image", "photo", "scan", "attachment", "show", "open",
    "view", "download", "picture", "copy", "upload", "uploaded", "extract",
}


def _route_kind(question: str, okf_matches: list[dict[str, object]]) -> str:
    """Name the evidence route selected for a request."""
    has_database = any(
        isinstance(item.get("metadata", {}).get("database"), dict)
        or item.get("metadata", {}).get("kind") == "database"
        for item in okf_matches
    )
    if not has_database:
        return "document"
    return "hybrid" if _tokens(question) & _DOCUMENT_INTENT else "database"


def _okf_context(
    question: str, settings: Settings, client: OpenAI | None
) -> list[dict[str, object]]:
    """Resolve a curated concept, querying its mapped database table when configured."""
    with timed_stage("okf_match"):
        matches = search_bundle(question, settings.okf_directory)
    database_matches = [
        match for match in matches
        if isinstance(match.get("metadata", {}).get("database"), dict)
    ]
    if database_matches:
        # OKF selects a schema-aware plan or a fixed mapping. The model never supplies
        # executable SQL; the natural planner validates identifiers and compiles SELECT.
        selected = database_matches[0]
        metadata = selected["metadata"]
        mapping = metadata["database"]
        if mapping.get("nl_to_sql"):
            return lookup_postgres_natural(
                question, settings, client, str(metadata.get("title", "database concept"))
            )
        return lookup_postgres(
            question,
            mapping,
            settings,
            str(metadata.get("title", "database concept")),
        )
    return matches


def _follow_up_crew_question(question: str, history: list[dict[str, str]] | None) -> str:
    """Carry a crew code into short follow-ups that refer to the current crew."""
    if re.search(r"\b\d{6,12}\b", question) or not history:
        return question
    question_tokens = _tokens(question)
    if not question_tokens.intersection({
        "crew", "certificate", "license", "licence", "document", "passport",
        "medical", "sbook", "seaman", "cdc", "payroll", "salary", "bank",
        "address", "pay", "earning", "deduction",
    }):
        return question
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        content = str(turn.get("content", ""))
        if not _tokens(content).intersection({"crew", "crewcode", "code"}):
            continue
        match = re.search(r"\b\d{6,12}\b", content)
        if match:
            return f"{question} crew code {match.group(0)}"
    return question


def _retrieve_matches(collection, question_embedding: list[float]) -> list[dict[str, object]]:
    """Retrieve relevant distinct evidence without letting one source dominate."""
    matches = retrieve(collection, question_embedding, n_results=12)
    matches.extend(retrieve(collection, question_embedding, n_results=12, where={"kind": "image"}))
    unique: dict[tuple[str, str, str], dict[str, object]] = {}
    for match in matches:
        metadata = match["metadata"]
        key = (str(metadata.get("source", "")), str(metadata.get("location", "")), str(match["text"]))
        current = unique.get(key)
        if current is None or float(match.get("distance", 0)) < float(current.get("distance", 0)):
            unique[key] = match
    # Keep repeated pages from one large PDF from crowding out other certificates.
    ranked = sorted(
        (match for match in unique.values() if float(match.get("distance", 1.0)) <= 0.65),
        key=lambda match: float(match.get("distance", 0)),
    )
    selected: list[dict[str, object]] = []
    source_counts: dict[str, int] = {}
    for match in ranked:
        source = str(match["metadata"].get("source", ""))
        if source_counts.get(source, 0) >= 2:
            continue
        selected.append(match)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= 8:
            break
    return selected


def _question_context(
    question: str,
    settings: Settings,
    client: OpenAI | None,
    empty_message: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    """Route to OKF, combine live database evidence with document RAG, or use document RAG."""
    database_question = _follow_up_crew_question(question, history)
    with timed_stage("routing"):
        okf_matches = _okf_context(database_question, settings, client)
    route = _route_kind(database_question, okf_matches)
    logger.info("request_route route=%s", route)
    if okf_matches:
        if route in {"database", "hybrid"} and any(
            item.get("metadata", {}).get("kind") == "database" for item in okf_matches
        ):
            if any(item.get("metadata", {}).get("needs_identifier") for item in okf_matches):
                return okf_matches
            if (
                any(item.get("metadata", {}).get("no_records") for item in okf_matches)
                and re.search(r"\b\d{6,12}\b", database_question)
            ):
                return okf_matches
            no_linked_items = [
                item for item in okf_matches
                if item.get("metadata", {}).get("no_linked_records")
            ]
            # A code-resolved crew with no linked record must not be paired with
            # semantically similar documents belonging to another person.
            if no_linked_items and re.search(r"\b\d{6,12}\b", database_question):
                return okf_matches
            try:
                collection = get_provider_collection(settings)
                if collection.count():
                    with timed_stage("embedding"):
                        embedding = get_embeddings([question], settings, client)[0]
                    no_record_items = [
                        item for item in okf_matches
                        if item.get("metadata", {}).get("no_records")
                    ]
                    no_certificate_items = [
                        item for item in okf_matches
                        if item.get("metadata", {}).get("no_certificates")
                    ]
                    question_tokens = _tokens(question)
                    asks_for_certificate_details = bool(
                        question_tokens & {"certificate", "license", "licence", "proficiency", "competency"}
                    )
                    should_search_documents = bool(no_record_items) or (
                        bool(no_certificate_items) and asks_for_certificate_details
                    )
                    if no_certificate_items and not asks_for_certificate_details and not no_record_items:
                        return okf_matches
                    document_matches = None
                    if should_search_documents:
                        # Only fall back to uploaded documents when they mention the requested
                        # person's name; nearest-neighbor similarity alone can return another person.
                        with timed_stage("retrieval"):
                            document_matches = _retrieve_matches(collection, embedding)
                        fallback_item = (no_record_items or no_certificate_items)[0]
                        requested_terms = set(fallback_item.get("metadata", {}).get("query_terms", []))
                        matching_documents = [
                            item for item in document_matches
                            if requested_terms and requested_terms.issubset(_tokens(
                                str(item.get("metadata", {}).get("source", "")) + " "
                                + str(item.get("text", ""))
                            ))
                        ]
                        if matching_documents:
                            return matching_documents
                    if document_matches is None:
                        with timed_stage("retrieval"):
                            supplemental = _retrieve_matches(collection, embedding)
                    else:
                        supplemental = document_matches
                    linked_names = {
                        Path(str(name).replace("\\", "/")).name.casefold()
                        for item in okf_matches
                        for name in (
                            *item.get("metadata", {}).get("document_names", []),
                            *item.get("metadata", {}).get("media_paths", []),
                        )
                    }
                    # Supplement with document text only when its filename is explicitly
                    # linked to a matched database record.
                    okf_matches.extend(
                        item for item in supplemental
                        if Path(str(item.get("metadata", {}).get("source", ""))).name.casefold()
                        in linked_names
                    )
            except Exception:
                # A live database answer remains useful if optional document retrieval is unavailable.
                logger.exception("Document retrieval failed alongside a database lookup")
        return okf_matches

    with timed_stage("routing"):
        collection = get_provider_collection(settings)
        if collection.count() == 0:
            raise RuntimeError(empty_message)
    with timed_stage("embedding"):
        question_embedding = get_embeddings([question], settings, client)[0]
    with timed_stage("retrieval"):
        return _retrieve_matches(collection, question_embedding)


def index_pdfs(settings: Settings, client: OpenAI | None = None) -> int:
    """Load supported documents, extract modality content, embed, and store it."""
    with timed_stage("document_load"):
        blocks = load_documents(settings.pdf_directory, settings)
    with timed_stage("chunking"):
        chunks = chunk_pages(blocks)
    if not chunks:
        raise ValueError("No searchable text could be extracted from the documents")
    collection = get_provider_collection(settings)
    # Stable content IDs allow unchanged chunks to remain while new or changed chunks
    # are embedded. Remove only IDs no longer represented by the current source set.
    with timed_stage("index_reconcile"):
        current_ids = {str(chunk["id"]) for chunk in chunks}
        existing = collection.get(include=["metadatas"])
        existing_ids = list(existing.get("ids", []))
        existing_metadata = existing.get("metadatas", []) or []
        existing_sources = {
            str(metadata.get("source", "")) for metadata in existing_metadata if metadata
        }
        current_sources = {str(chunk.get("source", "")) for chunk in chunks}
        source_ids: dict[str, set[str]] = {}
        for chunk in chunks:
            source_ids.setdefault(str(chunk.get("source", "")), set()).add(str(chunk["id"]))
        existing_by_source: dict[str, set[str]] = {}
        for identifier, metadata in zip(existing_ids, existing_metadata):
            if metadata:
                existing_by_source.setdefault(str(metadata.get("source", "")), set()).add(str(identifier))
        stale_ids = set()
        for source in existing_sources | current_sources:
            stale_ids.update(existing_by_source.get(source, set()) - source_ids.get(source, set()))
        if stale_ids:
            collection.delete(ids=sorted(stale_ids))
        existing_ids_set = set(existing_ids) - stale_ids
        new_chunks = [chunk for chunk in chunks if str(chunk["id"]) not in existing_ids_set]
    if new_chunks:
        with timed_stage("embedding"):
            embeddings = get_embeddings([str(chunk["text"]) for chunk in new_chunks], settings, client)
        with timed_stage("vector_store"):
            store_chunks(collection, new_chunks, embeddings)
    return len(chunks)


def ask(
    question: str,
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Retrieve relevant context and generate an answer for a question."""
    if not question.strip():
        raise ValueError("Question cannot be empty")
    with timed_stage("context"):
        matches = _question_context(
            question, settings, client, "The vector store is empty. Run the index command first.", history
        )
    with timed_stage("generation"):
        return generate_answer(question, matches, settings, client, history)


def ask_stream(
    question: str,
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> Iterator[str]:
    """Retrieve relevant PDF passages, then stream the generated answer."""
    if not question.strip():
        raise ValueError("Question cannot be empty")
    matches = _question_context(
        question, settings, client,
        "The vector store is empty. Add a PDF and wait for indexing to finish.",
        history,
    )
    return stream_answer(question, matches, settings, client, history)


def ask_stream_with_media(
    question: str,
    settings: Settings,
    client: OpenAI | None = None,
    history: list[dict[str, str]] | None = None,
) -> Iterator[dict[str, object]]:
    """Stream an answer followed by references to matching uploaded media."""
    if not question.strip():
        raise ValueError("Question cannot be empty")
    matches = _question_context(
        question, settings, client,
        "The vector store is empty. Add a document and wait for indexing to finish.",
        history,
    )

    root = settings.pdf_directory.resolve()
    media: list[dict[str, str]] = []
    seen: set[str] = set()
    database_matches = [
        match for match in matches
        if match.get("metadata", {}).get("kind") == "database"
    ]
    # Database answers may display only files explicitly linked to the matched DB rows.
    # Semantically similar vector images are not reliable evidence of a person's identity.
    if database_matches:
        allowed_media = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
                         ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
        for match in database_matches:
            metadata = match.get("metadata", {})
            paths = metadata.get("media_paths", [])
            names = metadata.get("document_names", [])
            for index, candidate in enumerate(paths):
                source = Path(str(candidate or ""))
                if len(media) >= 4:
                    break
                if str(candidate) in seen:
                    continue
                seen.add(str(candidate))
                name = str(names[index]) if index < len(names) else source.name or "certificate"
                local_file = None
                for local_name in (name, source.name):
                    if not local_name:
                        continue
                    exact = (root / Path(local_name).name).resolve()
                    if exact.is_relative_to(root) and exact.is_file() and exact.suffix.lower() in allowed_media:
                        local_file = exact
                        break
                if local_file is None:
                    stems = {Path(value).stem.casefold() for value in (name, source.name) if value}
                    possible = [file for file in root.iterdir()
                                if file.is_file() and file.suffix.lower() in allowed_media
                                and file.stem.casefold() in stems]
                    if len(possible) == 1:
                        local_file = possible[0].resolve()
                if local_file is not None:
                    display_name = local_file.name
                    extension = local_file.suffix.lower()
                    url = f"/api/media/{quote(display_name)}"
                elif settings.database_media_base_url:
                    display_name = name
                    extension = source.suffix.lower()
                    token = register_media_path(str(candidate))
                    url = f"/api/database-media/{token}"
                else:
                    continue
                kind = "video" if extension in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"} else ("image" if extension in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"} else "document")
                media.append({"name": display_name, "url": url, "type": kind, "location": ""})
    else:
        candidate_paths = [match.get("metadata", {}).get("source", "") for match in matches]
        for candidate in candidate_paths:
            source = Path(str(candidate or ""))
            if source.suffix.lower() not in {
                ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
                ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
            }:
                continue
            try:
                resolved = (source if source.is_absolute() else root / source).resolve()
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
            except (OSError, ValueError):
                continue
            name = resolved.name
            if name in seen:
                continue
            seen.add(name)
            media.append({
                "name": name,
                "url": f"/api/media/{quote(name)}",
                "type": "video" if source.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"} else "image",
                "location": "",
            })
            if len(media) >= 4:
                break
    with timed_stage("generation"):
        for text in stream_answer(question, matches, settings, client, history):
            yield {"type": "text", "text": text}
    yield {"type": "media", "media": media}
