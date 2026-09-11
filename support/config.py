"""
Support Module Configuration.
Independent configuration settings for file upload limits, MIME types, extensions,
default issue SLAs, and initial category seeds.
"""

import os
from pathlib import Path

# Attachments live under the same uploads root as the rest of the app (LMS_UPLOAD_FOLDER,
# defaulting to <repo>/uploads) unless SUPPORT_UPLOAD_DIR overrides it explicitly.
_uploads_root = os.getenv("LMS_UPLOAD_FOLDER", str(Path(__file__).resolve().parent.parent / "uploads"))
SUPPORT_UPLOAD_DIR = Path(os.getenv("SUPPORT_UPLOAD_DIR", str(Path(_uploads_root) / "support")))


def _mb_env(name, default_mb):
    """An attachment-size limit in MB, overridable via env var, returned in bytes."""
    try:
        return int(os.getenv(name, str(default_mb))) * 1024 * 1024
    except ValueError:
        return default_mb * 1024 * 1024


# Allowed file extensions and maximum size limits (in bytes). Defaults are deliberately much
# smaller than a typical helpdesk tool's: this app's usual home is a 512MB free-tier disk
# quota (PythonAnywhere), where a handful of 100MB video attachments would consume the whole
# thing. Raise SUPPORT_MAX_*_MB if you have real disk to spare (e.g. a paid host with a
# persistent volume).
ATTACHMENT_CONFIG = {
    "images": {
        "extensions": {"jpg", "jpeg", "png", "gif", "webp"},
        "mimes": {"image/jpeg", "image/png", "image/gif", "image/webp"},
        "max_size_bytes": _mb_env("SUPPORT_MAX_IMAGE_MB", 5)
    },
    "videos": {
        "extensions": {"mp4", "mov", "avi", "webm", "mkv"},
        "mimes": {"video/mp4", "video/quicktime", "video/x-msvideo", "video/webm", "video/x-matroska"},
        "max_size_bytes": _mb_env("SUPPORT_MAX_VIDEO_MB", 15)
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
        "max_size_bytes": _mb_env("SUPPORT_MAX_DOCUMENT_MB", 10)
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

# Largest of the per-category limits above, used as a fallback ceiling.
MAX_FILE_SIZE_BYTES = max(cfg["max_size_bytes"] for cfg in ATTACHMENT_CONFIG.values())

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

# Extra categories for the floating feedback widget (a lighter-weight entry point than the full
# "Report an issue" form). Seeded unconditionally -- see init_support_db() -- rather than only
# when the categories table is empty, so they land on databases that already seeded the original
# list before this feature existed.
ADDITIONAL_CATEGORIES = [
    ("Bug Report", "BUG_REPORT", "Something is broken or not working as expected."),
    ("Feature Request", "FEATURE_REQUEST", "An idea or enhancement request."),
    ("General Feedback", "GENERAL_FEEDBACK", "General comments or questions about the app.")
]

# Maps the widget's compact "type" segmented control to a real category code above.
FEEDBACK_WIDGET_CATEGORY_CODES = {
    "bug": "BUG_REPORT",
    "enhancement": "FEATURE_REQUEST",
    "question": "GENERAL_FEEDBACK"
}
