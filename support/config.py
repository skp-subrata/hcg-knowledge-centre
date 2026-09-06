"""
Support Module Configuration.
Independent configuration settings for file upload limits, MIME types, extensions,
default issue SLAs, and initial category seeds.
"""

import os
from pathlib import Path

# Base upload directory for support attachments
SUPPORT_UPLOAD_DIR = Path(os.getenv("SUPPORT_UPLOAD_DIR", Path(__file__).resolve().parent.parent / "uploads" / "support"))

# Allowed file extensions and maximum size limits (in bytes)
ATTACHMENT_CONFIG = {
    "images": {
        "extensions": {"jpg", "jpeg", "png", "gif", "webp"},
        "mimes": {"image/jpeg", "image/png", "image/gif", "image/webp"},
        "max_size_bytes": 10 * 1024 * 1024  # 10 MB
    },
    "videos": {
        "extensions": {"mp4", "mov", "avi", "webm", "mkv"},
        "mimes": {"video/mp4", "video/quicktime", "video/x-msvideo", "video/webm", "video/x-matroska"},
        "max_size_bytes": 100 * 1024 * 1024  # 100 MB
    },
    "documents": {
        "extensions": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv"},
        "mimes": {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
            "text/csv"
        },
        "max_size_bytes": 25 * 1024 * 1024  # 25 MB
    }
}

# Consolidated set of allowed extensions and MIMEs
ALLOWED_EXTENSIONS = (
    ATTACHMENT_CONFIG["images"]["extensions"] |
    ATTACHMENT_CONFIG["videos"]["extensions"] |
    ATTACHMENT_CONFIG["documents"]["extensions"]
)

ALLOWED_MIMES = (
    ATTACHMENT_CONFIG["images"]["mimes"] |
    ATTACHMENT_CONFIG["videos"]["mimes"] |
    ATTACHMENT_CONFIG["documents"]["mimes"]
)

# Max file size fallback (100 MB max for any file type)
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024

# Initial default categories seed
INITIAL_CATEGORIES = [
    ("Login / Authentication", "AUTH", "Issues related to sign-in, session timeouts, or password reset."),
    ("User Management", "USER_MGMT", "Account management, user creation, or permission issues."),
    ("Course", "COURSE", "Course content, video playback, document viewer, or thumbnail issues."),
    ("Assessment", "ASSESSMENT", "Pre/post assessments, questions, grading, or pass percentage issues."),
    ("Certificate", "CERTIFICATE", "Badge generation, certificate download, or score calculation issues."),
    ("Community", "COMMUNITY", "Posts, comments, ratings, or approval queue issues."),
    ("Notification", "NOTIFICATION", "Chime alerts, notification list, or unread badge issues."),
    ("Performance", "PERFORMANCE", "Slow loading, page lag, or timeout issues."),
    ("UI / Design", "UI_DESIGN", "Layout alignment, dark mode, or mobile responsive display issues."),
    ("API / Integration", "API", "API developer access, credentials, or documentation issues."),
    ("Data Issue", "DATA", "Missing records, history audit logs, or data mismatch."),
    ("File Upload", "FILE_UPLOAD", "Excel import, media upload, or file processing errors."),
    ("Mobile / Responsive", "MOBILE", "Touch controls, layout issues on mobile devices."),
    ("Other", "OTHER", "General inquiries or uncategorized issues.")
]

