import os
from pathlib import Path
from uuid import uuid4
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"pdf", "mp4", "webm", "mov", "avi", "mkv", "ppt", "pptx"}


def save_file(file_obj, folder: str) -> str:
    """Save an approved upload and return its generated filename."""
    original = secure_filename(file_obj.filename or "")
    extension = Path(original).suffix.lower().lstrip(".")
    if not original or extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type.")
    Path(folder).mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.{extension}"
    file_obj.save(Path(folder) / filename)
    return filename
