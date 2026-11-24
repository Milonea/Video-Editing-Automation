"""Guard the VEA source repository against project data and large media files."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath


MAX_TRACKED_FILE_BYTES = 50 * 1024 * 1024
MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mxf",
    ".mkv",
    ".avi",
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".prproj",
    ".mogrt",
    ".srt",
    ".vtt",
    ".xml",
}
PROJECT_DATA_DIRECTORIES = {
    "video_project",
    "videoprojects",
    "video-projects",
    "organized_video_sources",
    "incoming",
    "exports",
}


def audit_repository_entries(entries: Iterable[tuple[str, int | None]]) -> list[str]:
    """Return violations for Git paths and optional file sizes."""
    failures: list[str] = []
    for raw_path, size_bytes in entries:
        path = PurePosixPath(raw_path.replace("\\", "/"))
        parts = [part.casefold() for part in path.parts]
        if size_bytes == -1:
            failures.append(f"symbolic links are not allowed in the source repository: {raw_path}")
        if any(part in PROJECT_DATA_DIRECTORIES for part in parts):
            failures.append(f"project data path must not be tracked: {raw_path}")
        if path.suffix.casefold() in MEDIA_EXTENSIONS:
            failures.append(f"media or Premiere output must not be tracked: {raw_path}")
        if size_bytes is not None and size_bytes > MAX_TRACKED_FILE_BYTES:
            failures.append(f"tracked file exceeds {MAX_TRACKED_FILE_BYTES} bytes: {raw_path} ({size_bytes} bytes)")
    return failures
