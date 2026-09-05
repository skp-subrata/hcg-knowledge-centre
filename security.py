"""Small, dependency-free security helpers used by app.py.

Kept separate so they can be unit-tested without building the Flask app.
"""
import ipaddress
import os
import secrets
import socket
from pathlib import Path
from urllib.parse import urlparse

# File types a community post may attach. Course material goes through storage.py instead.
ALLOWED_ATTACHMENT_EXTENSIONS = {
	"pdf", "png", "jpg", "jpeg", "gif", "webp",
	"mp4", "webm", "mov",
	"ppt", "pptx", "doc", "docx", "xls", "xlsx", "csv", "txt", "zip",
}

# Only these are rendered inline by the browser when served from /uploads; everything else downloads.
INLINE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"}


def file_extension(filename):
	"""Lower-case extension without the dot ('' when there is none)."""
	return Path(filename or "").suffix.lower().lstrip(".")


def attachment_allowed(filename):
	return file_extension(filename) in ALLOWED_ATTACHMENT_EXTENSIONS


def serve_inline(filename):
	return file_extension(filename) in INLINE_EXTENSIONS


def load_or_create_secret_key(path):
	"""Return a stable secret key stored in *path*, creating it (mode 0600) on first use.

	Used when LMS_SECRET_KEY is not set, so sessions survive restarts without a
	hard-coded default that anyone reading the source could forge cookies with.
	"""
	path = Path(path)
	try:
		existing = path.read_text(encoding="utf-8").strip()
		if len(existing) >= 32:
			return existing
	except FileNotFoundError:
		pass
	key = secrets.token_hex(48)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(key, encoding="utf-8")
	try:
		os.chmod(path, 0o600)
	except OSError:
		pass
	return key


def _is_public_address(address):
	ip = ipaddress.ip_address(address)
	return not (
		ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
		or ip.is_reserved or ip.is_unspecified
	)


def is_safe_proxy_target(url, resolver=socket.getaddrinfo):
	"""True when *url* is an http(s) URL whose host resolves only to public addresses.

	Rejects file://, other schemes, empty hosts, and anything pointing at loopback,
	private, link-local or otherwise non-routable addresses (SSRF guard).
	"""
	try:
		parsed = urlparse(url or "")
	except ValueError:
		return False
	if parsed.scheme not in ("http", "https") or not parsed.hostname:
		return False
	hostname = parsed.hostname
	try:
		infos = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
	except (socket.gaierror, UnicodeError, OSError):
		return False
	addresses = {info[4][0] for info in infos}
	if not addresses:
		return False
	try:
		return all(_is_public_address(address) for address in addresses)
	except ValueError:
		return False
