"""
Attachment Service.
Handles file uploads, storage, MIME type validation, and secure paths for support issues.
"""

import os
from uuid import uuid4
from werkzeug.utils import secure_filename
from support.config import SUPPORT_UPLOAD_DIR, ATTACHMENT_CONFIG
from support.repositories import issue_repository


def validate_file(file_obj):
    """
    Validate file extension, mime type, and file size limits.
    Returns (is_valid, error_message).
    """
    if not file_obj or not file_obj.filename:
        return False, "No file provided."

    original_filename = secure_filename(file_obj.filename)
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""

    if not ext:
        return False, "Files without an extension are not allowed."

    # Determine file type category & validate
    category = None
    for cat_name, config in ATTACHMENT_CONFIG.items():
        if ext in config["extensions"]:
            category = cat_name
            break

    if not category:
        return False, f"File extension '.{ext}' is not supported."

    # Check file size limit
    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()
    file_obj.seek(0)

    max_size = ATTACHMENT_CONFIG[category]["max_size_bytes"]
    if file_size > max_size:
        limit_mb = max_size // (1024 * 1024)
        return False, f"File exceeds maximum allowed size of {limit_mb} MB for {category}."

    # Check MIME type
    content_type = getattr(file_obj, "content_type", "") or ""
    allowed_mimes = ATTACHMENT_CONFIG[category]["mimes"]
    if content_type and content_type.lower() not in allowed_mimes:
        # Fallback check if browser provided generic application/octet-stream
        if content_type.lower() != "application/octet-stream":
            return False, f"File format '{content_type}' is not permitted for {category}."

    return True, None


def save_attachment(connection, issue_id, file_obj, user_id, update_id=None):
    """
    Save an uploaded attachment to disk and insert database record.
    Returns the attachment record dict.
    """
    is_valid, err_msg = validate_file(file_obj)
    if not is_valid:
        raise ValueError(err_msg)

    orig_name = secure_filename(file_obj.filename)
    ext = orig_name.rsplit(".", 1)[-1].lower()
    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()
    file_obj.seek(0)

    # Generate unique stored filename
    stored_name = f"att_{issue_id}_{uuid4().hex[:10]}.{ext}"

    # Target directory structure: uploads/support/<issue_id>/
    issue_dir = SUPPORT_UPLOAD_DIR / str(issue_id)
    issue_dir.mkdir(parents=True, exist_ok=True)

    file_path = issue_dir / stored_name
    file_obj.save(file_path)

    # Relative file URL for internal routing
    file_url = f"/api/support/attachments/file/{issue_id}/{stored_name}"

    mime_type = getattr(file_obj, "content_type", "") or f"application/{ext}"

    attachment_data = {
        "issue_id": issue_id,
        "update_id": update_id,
        "uploaded_by_user_id": user_id,
        "original_file_name": orig_name,
        "stored_file_name": stored_name,
        "file_path": str(file_path),
        "file_url": file_url,
        "mime_type": mime_type,
        "file_extension": ext,
        "file_size": file_size,
        "storage_provider": "LOCAL"
    }

    attachment_id = issue_repository.add_attachment(connection, attachment_data)
    attachment_data["attachment_id"] = attachment_id
    return attachment_data

