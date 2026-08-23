from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import bad_request

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_RIFF = b"RIFF"
WEBP_WEBP = b"WEBP"

MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_WEBP = "image/webp"

ALLOWED_MIMES = frozenset({MIME_JPEG, MIME_PNG, MIME_WEBP})

_EXT_BY_MIME = {
    MIME_JPEG: "jpg",
    MIME_PNG: "png",
    MIME_WEBP: "webp",
}


def _detect_mime(header: bytes) -> str | None:
    if header.startswith(JPEG_MAGIC):
        return MIME_JPEG
    if header.startswith(PNG_MAGIC):
        return MIME_PNG
    if len(header) >= 12 and header[:4] == WEBP_RIFF and header[8:12] == WEBP_WEBP:
        return MIME_WEBP
    return None


def storage_root() -> Path:
    settings = get_settings()
    root = Path(settings.receipt_storage_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_storage_key(family_id: UUID, receipt_id: UUID, mime_type: str) -> str:
    ext = _EXT_BY_MIME.get(mime_type, "bin")
    return f"{family_id}/{receipt_id}.{ext}"


def absolute_path(storage_key: str) -> Path:
    root = storage_root().resolve()
    path = (root / storage_key).resolve()
    if not str(path).startswith(str(root)):
        raise bad_request("Invalid storage key")
    return path


def save_upload(file: UploadFile, *, family_id: UUID, receipt_id: UUID) -> tuple[str, str, int]:
    """Stream an upload to disk. Returns (storage_key, mime_type, byte_size)."""
    settings = get_settings()
    max_bytes = settings.receipt_max_bytes

    header = file.file.read(16)
    if not header:
        raise bad_request("Empty file", code="empty_file")
    mime_type = _detect_mime(header)
    if mime_type is None:
        raise bad_request("Unsupported image type. Use JPEG, PNG, or WebP.", code="unsupported_media")

    storage_key = build_storage_key(family_id, receipt_id, mime_type)
    path = absolute_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)

    size = len(header)
    with path.open("wb") as out:
        out.write(header)
        while True:
            chunk = file.file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                path.unlink(missing_ok=True)
                raise bad_request(
                    f"File exceeds maximum size of {max_bytes} bytes",
                    code="file_too_large",
                )
            out.write(chunk)

    return storage_key, mime_type, size


def read_bytes(storage_key: str) -> bytes:
    path = absolute_path(storage_key)
    if not path.is_file():
        raise bad_request("Receipt image not found on disk", code="missing_file")
    return path.read_bytes()


def delete_file(storage_key: str) -> None:
    path = absolute_path(storage_key)
    path.unlink(missing_ok=True)
    parent = path.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
