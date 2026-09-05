"""Unit tests for security.py (no Flask app involved)."""
import socket

import pytest

import security


def fake_resolver(mapping):
	def _resolve(host, port, proto=None):
		if host not in mapping:
			raise socket.gaierror("unknown host")
		return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in mapping[host]]

	return _resolve


PUBLIC = fake_resolver({"example.com": ["93.184.216.34"], "dual.example": ["93.184.216.34", "10.0.0.5"]})


@pytest.mark.parametrize("url", ["https://example.com/page", "http://example.com:8080/x?y=1"])
def test_public_http_urls_are_allowed(url):
	assert security.is_safe_proxy_target(url, resolver=PUBLIC)


@pytest.mark.parametrize("url", [
	"file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "", None, "http://", "javascript:alert(1)",
	"http://127.0.0.1:5050/", "http://[::1]/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
	"http://192.168.1.1/", "http://0.0.0.0/", "http://dual.example/",  # one private address is enough to refuse
	"http://unknown.host/",
])
def test_unsafe_targets_are_refused(url):
	resolver = fake_resolver({"dual.example": ["93.184.216.34", "10.0.0.5"], "example.com": ["93.184.216.34"]})
	assert not security.is_safe_proxy_target(url, resolver=resolver)


def test_literal_ip_hosts_do_not_need_dns():
	assert security.is_safe_proxy_target("http://93.184.216.34/", resolver=fake_resolver({"93.184.216.34": ["93.184.216.34"]}))
	assert not security.is_safe_proxy_target("http://127.0.0.1/", resolver=fake_resolver({"127.0.0.1": ["127.0.0.1"]}))


@pytest.mark.parametrize("name, allowed", [
	("report.pdf", True), ("photo.JPG", True), ("deck.pptx", True), ("archive.zip", True),
	("evil.html", False), ("page.HTM", False), ("script.js", False), ("run.sh", False), ("app.py", False),
	("vector.svg", False), ("noext", False), ("", False), (None, False),
])
def test_attachment_allowlist(name, allowed):
	assert security.attachment_allowed(name) is allowed


def test_inline_only_for_media():
	assert security.serve_inline("a.pdf") and security.serve_inline("b.PNG") and security.serve_inline("c.mp4")
	assert not security.serve_inline("d.docx") and not security.serve_inline("e.zip") and not security.serve_inline("f.html")


def test_secret_key_is_created_once_and_reused(tmp_path):
	path = tmp_path / "secrets" / ".secret_key"
	first = security.load_or_create_secret_key(path)
	second = security.load_or_create_secret_key(path)
	assert first == second and len(first) >= 64 and first != "change-this-local-secret"
	assert oct(path.stat().st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------------------
# sanitize_html
# ---------------------------------------------------------------------------
from security import sanitize_html  # noqa: E402


def test_sanitizer_keeps_quill_formatting():
	html = '<p>Hello <strong>bold</strong> <em>it</em> <u>u</u> <s>s</s></p><ol><li>one</li></ol><blockquote>q</blockquote><pre class="ql-syntax">x</pre><h2>Title</h2><p><br></p>'
	assert sanitize_html(html) == html


def test_sanitizer_removes_scripts_and_their_content():
	assert sanitize_html('<p>ok</p><script>alert(1)</script><p>after</p>') == "<p>ok</p><p>after</p>"
	assert sanitize_html('<style>p{display:none}</style><iframe src="x"></iframe>text') == "text"


def test_sanitizer_drops_event_handlers_and_unsafe_urls():
	assert sanitize_html('<img src=x onerror="alert(1)">') == "<img>"
	assert sanitize_html('<a href="javascript:alert(1)">x</a>') == "<a>x</a>"
	assert sanitize_html('<a href="JAVASCRIPT:alert(1)">x</a>') == "<a>x</a>"
	assert sanitize_html('<a href="data:text/html;base64,AAAA">x</a>') == "<a>x</a>"
	assert sanitize_html('<p style="color:red" onclick="x()">t</p>') == "<p>t</p>"


def test_sanitizer_keeps_safe_links_and_images():
	assert sanitize_html('<a href="https://example.com/x" target="_blank">x</a>') == '<a href="https://example.com/x" target="_blank" rel="noopener noreferrer">x</a>'
	assert sanitize_html('<a href="/community">x</a>') == '<a href="/community">x</a>'
	assert sanitize_html('<img src="https://example.com/a.png" alt="a">') == '<img src="https://example.com/a.png" alt="a">'
	assert sanitize_html('<img src="data:image/png;base64,iVBORw0KGgo=">') == '<img src="data:image/png;base64,iVBORw0KGgo=">'


def test_sanitizer_escapes_text_and_closes_tags():
	assert sanitize_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"
	assert sanitize_html("<b>unclosed") == "<b>unclosed</b>"
	assert sanitize_html("<p>x<!-- comment --></p>") == "<p>x</p>"
	assert sanitize_html("<div><p>nested</div>") == "<div><p>nested</p></div>"
	assert sanitize_html(None) == "" and sanitize_html("") == ""


def test_sanitizer_drops_unknown_tags_but_keeps_their_text():
	assert sanitize_html("<marquee>hi</marquee><custom-el>there</custom-el>") == "hithere"
	assert sanitize_html('<svg onload="alert(1)"><circle/></svg>after') == "after"
