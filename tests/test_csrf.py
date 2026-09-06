"""CSRF protection (Phase 4): every session form and fetch carries a token; API-key requests are exempt."""
import re
from pathlib import Path

import pytest

import app as app_module

ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')


@pytest.fixture
def csrf_on(monkeypatch):
	monkeypatch.setitem(app_module.app.config, "CSRF_ENABLED", True)


def _token(client, path="/"):
	html = client.get(path).get_data(as_text=True)
	match = TOKEN_RE.search(html)
	assert match, "every page must expose the token in a meta tag"
	return match.group(1)


def test_form_post_without_token_is_rejected_and_has_no_effect(admin, csrf_on, db):
	before = db("SELECT COUNT(*) AS n FROM courses")[0]["n"]
	response = admin.post("/admin", data={"action": "add_course", "course_name": "Forged", "content_type": "URL", "content_url": "https://example.com"}, headers={"Referer": "http://localhost/admin"})
	assert response.status_code == 302 and response.headers["Location"].endswith("/admin")
	assert db("SELECT COUNT(*) AS n FROM courses")[0]["n"] == before
	assert b"expired for security reasons" in admin.get("/admin").data


def test_form_post_with_token_succeeds(admin, csrf_on, db):
	token = _token(admin, "/admin")
	admin.post("/admin", data={"action": "add_course", "course_name": "Genuine", "content_type": "URL", "content_url": "https://example.com", "csrf_token": token})
	assert db("SELECT COUNT(*) AS n FROM courses WHERE name = 'Genuine'")[0]["n"] == 1


def test_token_is_stable_within_a_session_and_differs_between_sessions(student, moderator, csrf_on):
	assert _token(student) == _token(student, "/profile")
	assert _token(student) != _token(moderator)


def test_ajax_post_without_token_gets_json_400(student, csrf_on, world, db):
	note = db("SELECT id FROM notifications WHERE user_id = ? LIMIT 1", (world.users["maya.student"],))
	if not note:
		pytest.skip("seed has no notification for the student")
	response = student.post(f"/api/notifications/{note[0]['id']}/read", headers={"X-Requested-With": "XMLHttpRequest"})
	assert response.status_code == 400 and "CSRF" in response.get_json()["error"]


def test_ajax_post_with_header_token_is_accepted(student, csrf_on, world, db):
	note = db("SELECT id FROM notifications WHERE user_id = ? LIMIT 1", (world.users["maya.student"],))
	if not note:
		pytest.skip("seed has no notification for the student")
	token = _token(student)
	response = student.post(f"/api/notifications/{note[0]['id']}/read", headers={"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": token})
	assert response.status_code == 200


def test_json_post_without_token_gets_json_400(student, csrf_on):
	response = student.post("/api/interests", json={"interest_name": "Forged"})
	assert response.status_code == 400 and response.is_json


def test_api_key_requests_are_exempt(anon, csrf_on, api_headers):
	response = anon.post("/api/v1/courses", json={"name": "Via API", "description": "d", "category": "c", "content_type": "URL", "content_url": "https://example.com", "status": "draft"}, headers=api_headers("admin"))
	assert response.status_code in (200, 201), response.get_data(as_text=True)


def test_login_works_with_the_token_from_the_login_page(anon, csrf_on):
	token = _token(anon)
	response = anon.post("/", data={"username": "admin", "password": "admin", "csrf_token": token})
	assert response.status_code == 302
	with anon.session_transaction() as sess:
		assert sess.get("user_id")


def test_login_without_token_is_rejected(anon, csrf_on):
	anon.post("/", data={"username": "admin", "password": "admin"})
	with anon.session_transaction() as sess:
		assert "user_id" not in sess


def test_logout_and_switch_role_are_post_only(admin, csrf_on):
	assert admin.get("/logout").status_code == 405
	assert admin.get("/switch-role").status_code == 405
	token = _token(admin)
	admin.post("/logout", data={"csrf_token": token})
	with admin.session_transaction() as sess:
		assert "user_id" not in sess


def test_wrong_token_is_rejected(admin, csrf_on, db):
	_token(admin)
	before = db("SELECT COUNT(*) AS n FROM courses")[0]["n"]
	admin.post("/admin", data={"action": "add_course", "course_name": "Forged", "content_type": "URL", "content_url": "https://example.com", "csrf_token": "not-the-token"})
	assert db("SELECT COUNT(*) AS n FROM courses")[0]["n"] == before


@pytest.mark.parametrize("template", sorted(p.name for p in (ROOT / "templates").glob("*.html")) + sorted("_partials/" + p.name for p in (ROOT / "templates" / "_partials").glob("*.html")))
def test_every_post_form_in_templates_carries_a_token(template):
	html = (ROOT / "templates" / template).read_text(encoding="utf-8")
	forms = re.findall(r'<form\b[^>]*\bmethod="post"[^>]*>', html, flags=re.I)
	tokens = html.count('name="csrf_token"')
	assert tokens == len(forms), f"{template}: {len(forms)} POST forms but {tokens} csrf_token inputs"


def test_mutating_fetches_send_the_header():
	for rel in ("static/js/app.js", "templates/profile.html", "templates/admin.html"):
		text = (ROOT / rel).read_text(encoding="utf-8")
		for match in re.finditer(r"fetch\((?:[^)(]|\((?:[^)(]|\([^)(]*\))*\))*\)", text, flags=re.S):
			call = match.group(0)
			if re.search(r"method:\s*['\"](POST|PUT|DELETE|PATCH)", call):
				assert "X-CSRF-Token" in call, f"{rel}: {call[:90]}"
