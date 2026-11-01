"""Read and deterministically route questions to an Open Knowledge Format bundle."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    "a", "about", "an", "and", "are", "can", "do", "does", "for", "from", "give",
    "how", "i", "in", "is", "it", "me", "my", "of", "on", "please", "show", "tell",
    "the", "to", "what", "when", "where", "which", "who", "why", "with", "you",
}


@dataclass(frozen=True)
class OKFConcept:
    """A Markdown concept and the metadata needed for routing and trust display."""

    concept_id: str
    title: str
    body: str
    metadata: dict[str, Any]
    path: Path


def _tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", value.lower())) - _STOP_WORDS
    return {token[:-1] if token.endswith("s") and len(token) > 4 else token for token in tokens}


def _frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        logger.warning("Skipping OKF concept without YAML frontmatter: %s", path)
        return None
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        logger.warning("Skipping OKF concept with unclosed YAML frontmatter: %s", path)
        return None
    try:
        metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        logger.exception("Skipping OKF concept with invalid YAML frontmatter: %s", path)
        return None
    if not isinstance(metadata, dict) or not str(metadata.get("type", "")).strip():
        logger.warning("Skipping OKF concept without a non-empty type: %s", path)
        return None
    return metadata, "\n".join(lines[end + 1 :]).strip()


def _trust_tier(verified: Any) -> str:
    if not verified:
        return "unverified"
    events = verified if isinstance(verified, list) else [verified]
    for event in events:
        if isinstance(event, dict) and str(event.get("by", "")).startswith("human:"):
            return "human-reviewed"
    return "machine-confirmed"


def _is_stale(value: Any) -> bool:
    if not value:
        return False
    try:
        if isinstance(value, datetime):
            stale_after = value
        elif isinstance(value, date):
            stale_after = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        else:
            stale_after = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stale_after.tzinfo is None:
            stale_after = stale_after.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= stale_after.astimezone(timezone.utc)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid OKF stale_after value: %r", value)
        return True


def load_bundle(bundle_path: Path) -> list[OKFConcept]:
    """Load OKF v0.1/v0.2-style Markdown concepts; reserved index/log files are skipped."""
    root = bundle_path.expanduser().resolve()
    if not root.is_dir():
        return []
    concepts: list[OKFConcept] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() in {"index.md", "log.md"}:
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            parsed = _frontmatter(resolved.read_text(encoding="utf-8"), resolved)
        except (OSError, UnicodeError) as error:
            logger.warning("Could not read OKF concept %s: %s", path, error)
            continue
        if parsed is None:
            continue
        metadata, body = parsed
        status = str(metadata.get("status", "stable")).lower()
        if status in {"draft", "deprecated"} or _is_stale(metadata.get("stale_after")):
            continue
        if not body and not str(metadata.get("description", "")).strip():
            logger.warning("Skipping empty OKF concept: %s", resolved)
            continue
        relative = resolved.relative_to(root).as_posix()
        title = str(metadata.get("title") or resolved.stem.replace("-", " ").replace("_", " ")).strip()
        concepts.append(OKFConcept(relative.removesuffix(".md"), title, body, metadata, resolved))
    return concepts


def search_bundle(question: str, bundle_path: Path, limit: int = 3) -> list[dict[str, Any]]:
    """Return high-confidence lexical and semantic OKF title/alias matches."""
    query_tokens = _tokens(question)
    if not query_tokens:
        return []
    candidates: list[tuple[float, int, OKFConcept]] = []
    for concept in load_bundle(bundle_path):
        aliases = concept.metadata.get("aliases", []) or []
        if isinstance(aliases, str):
            aliases = [aliases]
        titles = [concept.title, *aliases]
        title_sets = [_tokens(str(title)) for title in titles if str(title).strip()]
        title_sets = [tokens for tokens in title_sets if tokens]
        matched_alias_count = sum(tokens.issubset(query_tokens) for tokens in title_sets)
        path_tokens = _tokens(concept.concept_id.replace("/", " "))
        exact_title = any(tokens.issubset(query_tokens) for tokens in title_sets)
        exact_id = len(path_tokens) > 1 and path_tokens.issubset(query_tokens)
        if exact_title or exact_id:
            score = 1.0
        else:
            # Alias phrases often differ by inflection or word order. Require a
            # substantial phrase similarity and at least one shared content word.
            normalized_question = " ".join(sorted(query_tokens))
            semantic_scores = []
            for title, tokens in zip(titles, [_tokens(str(value)) for value in titles]):
                if not tokens or not (tokens & query_tokens):
                    continue
                overlap = len(tokens & query_tokens) / max(1, len(tokens))
                phrase = " ".join(sorted(tokens))
                semantic_scores.append(max(
                    SequenceMatcher(None, phrase, normalized_question).ratio(),
                    overlap,
                ))
            semantic_score = max(semantic_scores, default=0.0)
            # Tags are useful routing hints, but a single broad tag must not hijack RAG.
            tags = concept.metadata.get("tags", []) or []
            tag_tokens = _tokens(" ".join(map(str, tags))) if isinstance(tags, list) else _tokens(str(tags))
            title_tokens = set().union(*title_sets) if title_sets else set()
            overlap = len(query_tokens & title_tokens)
            coverage = overlap / len(title_tokens) if title_tokens else 0.0
            tag_overlap = len(query_tokens & tag_tokens)
            if len(title_tokens) >= 2 and coverage >= 0.8:
                score = 0.8 + (0.1 * coverage)
            elif len(tag_tokens) >= 2 and tag_overlap >= 2 and tag_overlap / len(tag_tokens) >= 0.8:
                score = 0.75
            elif semantic_score >= 0.65:
                score = 0.7 + min(0.08, semantic_score * 0.08)
            else:
                continue
        candidates.append((score, matched_alias_count, concept))

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
            _trust_tier(item[2].metadata.get("verified")) == "human-reviewed",
            item[2].title.lower(),
        ),
        reverse=True,
    )
    results: list[dict[str, Any]] = []
    for score, _, concept in candidates[:limit]:
        metadata = concept.metadata
        results.append({
            "text": concept.body,
            "distance": 1.0 - score,
            "metadata": {
                "source": f"OKF/{concept.concept_id}.md",
                "location": "OKF concept",
                "kind": "okf",
                "title": concept.title,
                "type": str(metadata.get("type", "Concept")),
                "description": str(metadata.get("description", "")),
                "trust_tier": _trust_tier(metadata.get("verified")),
                "status": str(metadata.get("status", "stable")),
                "generated": str(metadata.get("generated", metadata.get("timestamp", ""))),
                "sources": metadata.get("sources", []),
                "tags": metadata.get("tags", []),
                "database": metadata.get("database"),
            },
        })
    return results
