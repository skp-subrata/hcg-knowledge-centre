"""
Attachment Validator.
"""
from support.services.attachment_service import validate_file


def validate_attachment(file_obj):
    """Validate file extension, mime type, and file size."""
    return validate_file(file_obj)

