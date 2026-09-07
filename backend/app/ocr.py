"""Text recovery from images, so a screenshot can be dropped on the uploader.

An image only becomes useful to this app once it is text: the retriever is
BM25 plus a sentence embedder, and every answer is a verbatim quote from an
indexed passage. So an image that cannot be read is refused rather than stored
-- an un-searchable document that shows up in the index as if it worked is
worse than a clear rejection.

Two engines, tried in order, mirroring how `generation.py` picks its answerer:

1. `claude` -- used when ANTHROPIC_API_KEY is set. Best quality, works on any
   platform, and it reconstructs a screenshot of a TABLE as a markdown table,
   which matters here: `structure_aware` keeps a table row glued to its header
   row, and that property is the whole point of the chunker.
2. `macos-vision` -- Apple's on-device Vision framework. Offline, no model
   download, no API key, but it reads line by line and cannot recover table
   structure, so a screenshotted table arrives as flat lines.

OCR output is never presented as if it were typed. `transcribe` returns the
engine that produced it, the caller records that in the document's frontmatter,
and the UI shows it -- because a quote that traces back to a misread character
should be checkable against the original image.
"""
from __future__ import annotations

import base64
import os

# Extensions and magic-byte prefixes. Magic bytes are checked too, because a
# screenshot saved as `.dat` is still a screenshot.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif",
              ".tif", ".tiff", ".bmp"}

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

# Claude accepts these directly; anything else is converted before sending.
CLAUDE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

OCR_PROMPT = """Transcribe every piece of text in this image, exactly as \
written. Rules:

1. Reproduce text verbatim. Do not correct spelling, expand abbreviations, or \
rephrase. Error codes, flags and identifiers must be character-for-character.
2. If the image contains a table, output it as a markdown table, with the \
header row first and a `| --- |` separator row beneath it.
3. Preserve headings as markdown headings and lists as markdown lists.
4. Output only the transcription. No preamble, no description of the image, \
no commentary on what you see.
5. If the image contains no readable text at all, output exactly: NO_TEXT"""


def sniff_mime(filename: str, data: bytes) -> str | None:
    """Return an image mime type, or None if this is not an image."""
    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF carry 'ftyp' at offset 4 with a heic/heif/mif1 brand.
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"heif",
                                               b"mif1", b"msf1"):
        return "image/heic"
    ext = os.path.splitext(filename)[1].lower()
    return "image/unknown" if ext in IMAGE_EXTS else None


def is_image(filename: str, data: bytes) -> bool:
    return sniff_mime(filename, data) is not None


# --------------------------------------------------------------------------
# Engine 1: Claude vision
# --------------------------------------------------------------------------

def _to_claude_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Claude takes png/jpeg/gif/webp. Convert anything else (HEIC, TIFF, BMP)
    to PNG via Pillow, which ships with the image stack already."""
    if mime in CLAUDE_MIMES:
        return data, mime
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.open(BytesIO(data)).convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def transcribe_claude(data: bytes, mime: str) -> str | None:
    import anthropic

    payload, mime = _to_claude_image(data, mime)
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-opus-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime,
                                         "data": base64.b64encode(payload).decode()}},
            {"type": "text", "text": OCR_PROMPT},
        ]}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return None if text == "NO_TEXT" else text


# --------------------------------------------------------------------------
# Engine 2: Apple Vision, on device
# --------------------------------------------------------------------------

def transcribe_macos_vision(data: bytes) -> str | None:
    import Quartz
    import Vision
    from Foundation import NSData

    nsdata = NSData.dataWithBytes_length_(data, len(data))
    source = Quartz.CGImageSourceCreateWithData(nsdata, None)
    if source is None or Quartz.CGImageSourceGetCount(source) == 0:
        return None
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return None

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        image, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(1)          # 1 = accurate, 0 = fast
    request.setUsesLanguageCorrection_(True)
    ok, _ = handler.performRequests_error_([request], None)
    if not ok:
        return None

    lines = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()).strip())
    lines = [ln for ln in lines if ln]
    if not lines:
        return None

    # Emitted as a markdown list, one item per recognised text region.
    #
    # Vision reads line by line and its lines rarely end in a full stop, so as
    # plain text the sentence splitter in generation.py merges the whole
    # transcript into a single unquotable blob -- an answer then cites the
    # entire image instead of the one line that answers. A list item is a unit
    # boundary, and it is also an honest representation: these ARE discrete
    # regions the recogniser found, not sentences of running prose.
    return "\n".join(f"- {ln}" for ln in lines)


# --------------------------------------------------------------------------

def available_engines() -> list[str]:
    """Which OCR engines this process could actually use, best first."""
    out = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append("claude")
    try:
        import Vision  # noqa: F401

        out.append("macos-vision")
    except Exception:
        pass
    return out


def transcribe(filename: str, data: bytes) -> tuple[str, str]:
    """Return (text, engine_name), or raise RuntimeError with a reason.

    Engines are tried best-first and a failure falls through to the next, so a
    missing API key or an offline machine degrades instead of erroring.
    """
    mime = sniff_mime(filename, data) or "image/unknown"
    engines = available_engines()
    if not engines:
        raise RuntimeError(
            "no OCR engine is available on this server, so text cannot be read "
            "out of an image. Set ANTHROPIC_API_KEY, or install Apple Vision "
            "with `pip install pyobjc-framework-Vision` on macOS."
        )

    failures = []
    for engine in engines:
        try:
            text = (transcribe_claude(data, mime) if engine == "claude"
                    else transcribe_macos_vision(data))
        except Exception as exc:
            failures.append(f"{engine}: {type(exc).__name__}: {exc}")
            continue
        if text:
            return text, engine
        failures.append(f"{engine}: found no readable text")

    raise RuntimeError("; ".join(failures))
