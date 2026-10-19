"""Small HTTP helpers for a locally running Ollama server."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from collections.abc import Iterator


def ollama_request(base_url: str, endpoint: str, payload: dict | None = None) -> dict:
    """Send a JSON request to Ollama and turn connection errors into useful messages."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"Ollama error: {detail}") from error
    except URLError as error:
        raise RuntimeError(
            "Cannot connect to Ollama at "
            f"{base_url}. Install Ollama and make sure it is running."
        ) from error


def ollama_stream(base_url: str, endpoint: str, payload: dict) -> Iterator[str]:
    """Yield generated content as Ollama streams newline-delimited JSON."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            for line in response:
                if not line.strip():
                    continue
                chunk = json.loads(line.decode("utf-8"))
                if chunk.get("error"):
                    raise RuntimeError(f"Ollama error: {chunk['error']}")
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"Ollama error: {detail}") from error
    except URLError as error:
        raise RuntimeError(
            "Cannot connect to Ollama. Make sure Ollama is running and try again."
        ) from error
