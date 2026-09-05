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
