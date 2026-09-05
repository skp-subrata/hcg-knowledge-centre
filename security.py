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


def is_safe_proxy_target(url, resolver=None):
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
	resolver = resolver or socket.getaddrinfo  # looked up at call time so tests can fake DNS
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


# ---------------------------------------------------------------------------
# HTML sanitiser for rich-text post bodies (Quill output). Allow-list based, stdlib only.
# ---------------------------------------------------------------------------
import re
from html import escape
from html.parser import HTMLParser

ALLOWED_TAGS = {
	"p", "br", "hr", "strong", "b", "em", "i", "u", "s", "strike", "sub", "sup",
	"ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code",
	"a", "img", "span", "div", "table", "thead", "tbody", "tr", "th", "td",
}
VOID_TAGS = {"br", "hr", "img"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript"}
ALLOWED_ATTRIBUTES = {
	"a": {"href", "title", "target"},
	"img": {"src", "alt", "title", "width", "height"},
	"span": {"class"}, "div": {"class"}, "p": {"class"}, "pre": {"class"}, "code": {"class"},
	"ul": {"class"}, "ol": {"class"}, "li": {"class"}, "h1": {"class"}, "h2": {"class"}, "h3": {"class"},
	"td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"},
}
_SAFE_URL = re.compile(r"^(https?://|mailto:|/(?!/)|#)", re.I)
_SAFE_IMG = re.compile(r"^(https?://|/(?!/)|data:image/(png|jpe?g|gif|webp);base64,)", re.I)
_SAFE_CLASS = re.compile(r"^[\w\s-]*$")


class _Sanitizer(HTMLParser):
	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.out = []
		self.open_tags = []
		self.dropping = 0

	def handle_starttag(self, tag, attrs):
		tag = tag.lower()
		if tag in DROP_WITH_CONTENT:
			self.dropping += 1
			return
		if self.dropping or tag not in ALLOWED_TAGS:
			return
		rendered = []
		wants_noopener = False
		for name, value in attrs:
			name = name.lower()
			value = value if value is not None else ""
			if name not in ALLOWED_ATTRIBUTES.get(tag, set()):
				continue
			cleaned = "".join(ch for ch in value if ch not in "\x00\t\r\n").strip()
			if name == "href" and not _SAFE_URL.match(cleaned):
				continue
			if name == "src" and not _SAFE_IMG.match(cleaned):
				continue
			if name == "class" and not _SAFE_CLASS.match(cleaned):
				continue
			if name == "target":
				if cleaned != "_blank":
					continue
				wants_noopener = True
			rendered.append(f' {name}="{escape(cleaned, quote=True)}"')
		if wants_noopener:
			rendered.append(' rel="noopener noreferrer"')
		self.out.append(f"<{tag}{''.join(rendered)}>")
		if tag not in VOID_TAGS:
			self.open_tags.append(tag)

	def handle_startendtag(self, tag, attrs):
		self.handle_starttag(tag, attrs)

	def handle_endtag(self, tag):
		tag = tag.lower()
		if tag in DROP_WITH_CONTENT:
			self.dropping = max(0, self.dropping - 1)
			return
		if self.dropping or tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self.open_tags:
			return
		while self.open_tags:
			closing = self.open_tags.pop()
			self.out.append(f"</{closing}>")
			if closing == tag:
				break

	def handle_data(self, data):
		if not self.dropping:
			self.out.append(escape(data, quote=False))

	def handle_comment(self, data):
		pass

	def handle_decl(self, decl):
		pass

	def handle_pi(self, data):
		pass

	def result(self):
		self.close()
		while self.open_tags:
			self.out.append(f"</{self.open_tags.pop()}>")
		return "".join(self.out)


def sanitize_html(value):
	"""Keep only harmless formatting from user-supplied HTML; drop scripts, event handlers and unsafe URLs."""
	if not value:
		return ""
	sanitizer = _Sanitizer()
	sanitizer.feed(str(value))
	return sanitizer.result()
