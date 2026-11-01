"""Read-only PostgreSQL lookups defined by an OKF concept."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from .config import Settings
from .okf import _tokens

logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUERY_NOISE = {
    "certificate", "certification", "detail", "information", "document", "record",
    "person", "employee", "customer", "please", "tell", "show", "share", "find",
    "about", "name", "email", "phone", "contact", "address", "passport", "rank",
    "designation", "department", "dept", "status", "expiry", "validity",
    "have", "has", "had", "having", "certificate", "certificates",
    "crew", "crewcode", "code", "what", "who", "which", "get", "find", "know",
    "this", "these", "that", "those",
    "full", "complete", "entire", "all", "everything", "profile", "summary",
    "lincese",
}


def _identifier(value: Any, label: str) -> str:
    name = str(value or "")
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid PostgreSQL {label} in OKF configuration")
    return '"' + name.replace('"', '""') + '"'


def _columns(value: Any, label: str, aliases: set[str], root_alias: str) -> list[tuple[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"OKF database mapping must define {label} as a non-empty list")
    parsed: list[tuple[str, str]] = []
    for item in value:
        parts = str(item).split(".")
        if len(parts) == 1:
            alias, column = root_alias, parts[0]
        elif len(parts) == 2:
            alias, column = parts
        else:
            raise ValueError(f"Invalid PostgreSQL {label} reference in OKF configuration")
        if alias not in aliases:
            raise ValueError(f"Unknown table alias in OKF {label}")
        quoted = f"{_identifier(alias, label)}.{_identifier(column, label)}"
        parsed.append((str(item), quoted))
    return parsed


def lookup_postgres(
    question: str,
    mapping: dict[str, Any],
    settings: Settings,
    concept_title: str,
) -> list[dict[str, Any]]:
    """Search only the explicitly mapped table/columns in a read-only transaction."""
    if not settings.database_url:
        raise RuntimeError("A database-backed OKF concept requires DATABASE_URL in .env")

    schema = _identifier(mapping.get("schema", "public"), "schema")
    record_label = str(mapping.get("record_label", "license document")).strip() or "license document"
    table = _identifier(mapping.get("table"), "table")
    root_alias = str(mapping.get("alias", "base"))
    root_alias_sql = _identifier(root_alias, "table alias")
    aliases = {root_alias}
    from_sql = f"{schema}.{table} AS {root_alias_sql}"
    joins = mapping.get("joins", []) or []
    if not isinstance(joins, list):
        raise ValueError("OKF database joins must be a list")
    for join in joins:
        if not isinstance(join, dict):
            raise ValueError("Each OKF database join must be a mapping")
        join_alias = str(join.get("alias", ""))
        if join_alias in aliases:
            raise ValueError("OKF database join aliases must be unique")
        join_table = _identifier(join.get("table"), "joined table")
        join_alias_sql = _identifier(join_alias, "table alias")
        aliases.add(join_alias)
        join_columns = _columns([join.get("left"), join.get("right")], "join columns", aliases, root_alias)
        from_sql += (
            f" LEFT JOIN {schema}.{join_table} AS {join_alias_sql}"
            f" ON {join_columns[0][1]} = {join_columns[1][1]}"
        )
    search_refs = _columns(mapping.get("search_columns"), "search_columns", aliases, root_alias)
    return_refs = _columns(mapping.get("return_columns"), "return_columns", aliases, root_alias)
    raw_column_aliases = mapping.get("column_aliases", {}) or {}
    if not isinstance(raw_column_aliases, dict):
        raise ValueError("OKF database column_aliases must be a mapping")
    column_aliases: dict[str, list[str]] = {}
    for reference, values in raw_column_aliases.items():
        _columns([reference], "column_aliases", aliases, root_alias)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            raise ValueError("Each OKF column alias entry must be a list of phrases")
        field_name = str(reference).rsplit(".", 1)[-1]
        column_aliases[field_name] = [str(value) for value in values]
    presence_refs = _columns(
        [mapping["record_presence_column"]], "record_presence_column", aliases, root_alias
    ) if mapping.get("record_presence_column") else []
    media_refs = _columns(
        [mapping["media_path_column"]], "media_path_column", aliases, root_alias
    ) if mapping.get("media_path_column") else []
    required_refs = _columns(
        mapping.get("not_null_columns"), "not_null_columns", aliases, root_alias
    ) if mapping.get("not_null_columns") else []
    return_names = [reference.rsplit(".", 1)[-1] for reference, _ in return_refs]
    if len(set(return_names)) != len(return_names):
        raise ValueError("OKF database return column names must be unique")
    limit_value = mapping.get("limit", 8)
    if isinstance(limit_value, bool) or not isinstance(limit_value, int) or not 1 <= limit_value <= 50:
        raise ValueError("OKF database mapping limit must be an integer from 1 to 50")

    ignored = mapping.get("ignored_terms", [])
    if isinstance(ignored, str):
        ignored = [ignored]
    alias_phrases = [phrase for phrases in column_aliases.values() for phrase in phrases]
    ignored_terms = set(_tokens(" ".join(map(str, ignored)))) | _QUERY_NOISE | _tokens(" ".join(alias_phrases))
    terms = sorted(term for term in _tokens(question) if len(term) > 1 and term not in ignored_terms)
    if not terms:
        return []
    # Numeric identifiers are much stronger lookup keys than surrounding request
    # wording ("full details", "need passport", etc.); avoid scoring those words
    # as though they must also appear inside a database value.
    identifier_terms = [term for term in terms if term.isdigit()]
    query_terms = (identifier_terms or terms)[:12]

    # Query code is fixed here. OKF supplies validated identifiers and values are parameters.
    select_sql = [
        f'{reference_sql} AS {_identifier("__return_" + str(index), "column alias")}'
        for index, (_, reference_sql) in enumerate(return_refs)
    ]
    select_sql.extend(
        f'{reference_sql} AS {_identifier("__search_" + str(index), "column alias")}'
        for index, (_, reference_sql) in enumerate(search_refs)
    )
    if presence_refs:
        select_sql.append(f'{presence_refs[0][1]} AS "__presence"')
    if media_refs:
        select_sql.append(f'{media_refs[0][1]} AS "__media_path"')
    column_sql = ", ".join(select_sql)
    term_clauses: list[str] = []
    parameters: list[str] = []
    for term in query_terms:
        term_clauses.append("(" + " OR ".join(f"{column}::text ILIKE %s" for _, column in search_refs) + ")")
        parameters.extend([f"%{term}%"] * len(search_refs))
    sql = (
        f"SELECT {column_sql} FROM {from_sql} WHERE "
        + "(" + " OR ".join(term_clauses) + ")"
        + "".join(f" AND {column} IS NOT NULL" for _, column in required_refs)
        + " LIMIT %s"
    )
    parameters.append(limit_value)

    try:
        from pg8000 import dbapi
    except ImportError as error:
        raise RuntimeError("PostgreSQL support is not installed; install the project dependencies") from error

    parsed_url = urlsplit(settings.database_url)
    if parsed_url.scheme not in {"postgresql", "postgres"} or not parsed_url.hostname:
        raise ValueError("DATABASE_URL must be a PostgreSQL URL")
    database_name = unquote(parsed_url.path.lstrip("/").split("/", 1)[0])
    if not database_name or not parsed_url.username:
        raise ValueError("DATABASE_URL must include a database name and username")
    connection = None
    try:
        connection = dbapi.connect(
            user=unquote(parsed_url.username),
            password=unquote(parsed_url.password or ""),
            host=parsed_url.hostname,
            port=parsed_url.port or 5432,
            database=database_name,
            timeout=5,
        )
        cursor = connection.cursor()
        try:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(sql, parameters)
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
    except Exception:
        logger.exception("Read-only PostgreSQL lookup failed for OKF concept %s", concept_title)
        raise
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()

    def score(row: dict[str, Any]) -> int:
        content = " ".join(
            str(row.get(f"__search_{index}", "") or "").lower()
            for index in range(len(search_refs))
        )
        return sum(term in content for term in query_terms)

    rows.sort(key=score, reverse=True)
    if rows:
        best_score = score(rows[0])
        if len(query_terms) >= 2 and best_score < 2:
            rows = []
        else:
            rows = [row for row in rows if score(row) == best_score]
    if not rows:
        return [{
            "text": "The read-only database lookup returned no matching records.",
            "distance": 0.0,
            "metadata": {
                "kind": "database", "location": concept_title,
                "no_records": True, "query_terms": query_terms,
                "column_aliases": column_aliases,
            },
        }]
    if presence_refs and all(row.get("__presence") is None for row in rows):
        identity_rows = [
            {
                name: row.get(f"__return_{index}")
                for index, name in enumerate(return_names)
                if row.get(f"__return_{index}") is not None
            }
            for row in rows
        ]
        return [{
            "text": (
                f"Crew record found, with no linked {record_label} records. Crew details: "
                + json.dumps(identity_rows, ensure_ascii=False, default=str)
            ),
            "distance": 0.0,
            "metadata": {
                "kind": "database", "location": concept_title,
                "no_certificates": record_label == "license document",
                "no_linked_records": True, "record_label": record_label,
                "query_terms": query_terms,
                "column_aliases": column_aliases,
            },
        }]

    matches = []
    for row in rows:
        public_row = {
            name: row.get(f"__return_{index}")
            for index, name in enumerate(return_names)
        }
        serialized = json.dumps(public_row, ensure_ascii=False, default=str)
        media_paths = [str(row["__media_path"])] if row.get("__media_path") else []
        document_names = [
            str(public_row["document_name"])
        ] if public_row.get("document_name") else []
        matches.append({
            "text": serialized,
            "distance": 0.0,
            "metadata": {
                "kind": "database", "location": concept_title,
                "media_paths": media_paths, "document_names": document_names,
                "column_aliases": column_aliases,
            },
        })
    return matches
