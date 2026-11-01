"""Extract searchable text from PDFs, images, audio, and video using local tools."""

import base64
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from .config import Settings
from .document_loader import load_pdf
from .local_models import ollama_request

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SUPPORTED_EXTENSIONS = {".pdf", *IMAGE_EXTENSIONS, *AUDIO_EXTENSIONS, *VIDEO_EXTENSIONS}


def _describe_image(data: bytes, settings: Settings, prompt: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    response = ollama_request(
        settings.ollama_base_url,
        "/api/chat",
        {
            "model": settings.vision_model,
            "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
            "stream": False,
            "options": {"num_predict": 384},
        },
    )
    return response.get("message", {}).get("content", "").strip()


def _pdf_content(path: Path, settings: Settings) -> list[dict[str, object]]:
    content = load_pdf(path)
    reader = PdfReader(str(path))
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = page.images
        except Exception:
            continue
        for image_number, image in enumerate(images, start=1):
            try:
                description = _describe_image(
                    image.data,
                    settings,
                    "Describe this image, chart, diagram, or table for document search. "
                    "Read visible labels and values where possible. Be concise and factual.",
                )
            except Exception as error:
                raise RuntimeError(
                    f"Could not analyze an image in {path.name}, page {page_number}: {error}"
                ) from error
            if description:
                content.append(
                    {
                        "source": str(path.resolve()),
                        "location": f"page {page_number}, image {image_number}",
                        "kind": "image",
                        "text": f"Image description: {description}",
                    }
                )
    return content


@lru_cache(maxsize=1)
def _whisper_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "Audio indexing needs faster-whisper. Install it with "
            "`python -m pip install -e '.[media]'` and retry."
        ) from error
    return WhisperModel("small", device="cpu", compute_type="int8")


def _transcribe(path: Path) -> list[dict[str, object]]:
    try:
        import av

        with av.open(str(path)) as container:
            if not container.streams.audio:
                return []
    except ImportError as error:
        raise RuntimeError(
            "Audio indexing needs faster-whisper. Install it with "
            "`python -m pip install -e '.[media]'` and retry."
        ) from error
    except Exception as error:
        raise RuntimeError(f"Could not read audio from {path.name}: {error}") from error

    try:
        segments, _ = _whisper_model().transcribe(str(path), vad_filter=True)
        results = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                results.append(
                    {
                        "source": str(path.resolve()),
                        "location": f"{segment.start:.1f}s-{segment.end:.1f}s",
                        "kind": "audio",
                        "text": text,
                    }
                )
        return results
    except Exception as error:
        raise RuntimeError(f"Could not transcribe {path.name}: {error}") from error


def _video_content(path: Path, settings: Settings) -> list[dict[str, object]]:
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError(
            "Video indexing needs OpenCV. Install it with "
            "`python -m pip install -e '.[media]'` and retry."
        ) from error

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video {path.name}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 1
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if frame_count else 0
    # Sample one frame every 30 seconds, with a hard limit to keep local indexing bounded.
    timestamps = [i * 30 for i in range(min(20, max(1, int(duration // 30) + 1)))]
    results: list[dict[str, object]] = []
    try:
        for seconds in timestamps:
            capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            description = _describe_image(
                encoded.tobytes(),
                settings,
                "Describe this video frame for semantic search. Include visible actions, objects, "
                "on-screen text, and chart or slide details. Be concise and factual.",
            )
            if description:
                results.append(
                    {
                        "source": str(path.resolve()),
                        "location": f"{seconds:.0f}s",
                        "kind": "video_frame",
                        "text": f"Video frame description: {description}",
                    }
                )
    finally:
        capture.release()

    # faster-whisper/PyAV decodes the video's audio stream when one is present.
    results.extend(_transcribe(path))
    return results


def load_documents(directory: Path, settings: Settings) -> list[dict[str, object]]:
    """Extract searchable text blocks from all supported files in a directory."""
    if not directory.is_dir():
        raise NotADirectoryError(f"Document directory not found: {directory}")
    paths = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not paths:
        raise FileNotFoundError(f"No supported documents found in {directory}")

    blocks: list[dict[str, object]] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            blocks.extend(_pdf_content(path, settings))
        elif suffix in IMAGE_EXTENSIONS:
            description = _describe_image(
                path.read_bytes(), settings,
                "Describe this image, chart, diagram, or table for document search. "
                "Read visible labels and values where possible. Be concise and factual.",
            )
            if description:
                blocks.append({
                    "source": str(path.resolve()), "location": "image", "kind": "image",
                    "text": f"Image description: {description}",
                })
        elif suffix in AUDIO_EXTENSIONS:
            blocks.extend(_transcribe(path))
        elif suffix in VIDEO_EXTENSIONS:
            blocks.extend(_video_content(path, settings))
    return blocks
