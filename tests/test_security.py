"""Authorization and hardening: who may do what, and the SSRF / upload / cookie guards."""
import io

import pytest

import app as app_module


# ---------------------------------------------------------------------------
# Batch F - authorization
# ---------------------------------------------------------------------------
def test_moderator_cannot_generate_or_revoke_api_credentials(moderator, world, db):
	admin_id = world.users["admin"]
	before = db("SELECT id, status FROM api_credentials WHERE user_id = ?", (admin_id,))
	moderator.post("/admin", data={"action": "generate_api_creds", "target_user_id": admin_id})
	moderator.post("/admin", data={"action": "revoke_api_creds", "target_user_id": admin_id})
	after = db("SELECT id, status FROM api_credentials WHERE user_id = ?", (admin_id,))
	assert [tuple(r) for r in after] == [tuple(r) for r in before]
	assert after[0]["status"] == "active"


def test_moderator_admin_page_does_not_leak_api_secrets(moderator, world):
	page = moderator.get("/admin").get_data(as_text=True)
	assert "as_world_admin" not in page and "as_world_mod" not in page


def test_admin_page_shows_api_credentials_to_admins(admin, world):
	assert "as_world_admin" in admin.get("/admin").get_data(as_text=True)


def test_impersonating_admin_cannot_switch_role(admin, world):
	maya = world.users["maya.student"]
	assert admin.post(f"/admin/view-as/{maya}").status_code == 302
	with admin.session_transaction() as sess:
		assert sess["user_id"] == maya and sess["role"] == "basic user" and sess["impersonator_id"] == world.users["admin"]
		assert sess["actual_role"] == "basic user", "the impersonated user's real role, not the admin's"
	admin.get("/switch-role")
	with admin.session_transaction() as sess:
		assert sess["role"] == "basic user"
	assert admin.get("/admin").status_code == 302  # still locked out while impersonating


def test_exit_view_restores_the_administrator(admin, world):
	admin.post(f"/admin/view-as/{world.users['maya.student']}")
	admin.get("/admin/exit-view")
	with admin.session_transaction() as sess:
		assert sess["user_id"] == world.users["admin"]
		assert sess["role"] == "admin" and sess["actual_role"] == "admin"
		assert "impersonator_id" not in sess
	assert admin.get("/admin").status_code == 200


def test_inactive_user_cannot_log_in(anon, world, db, login):
	db("UPDATE users SET is_active = 0 WHERE username = 'student'")
	response = login(anon, "student")
	assert response.status_code == 200 and b"Invalid username or password" in response.data
	with anon.session_transaction() as sess:
		assert "user_id" not in sess


def test_reviewer_cannot_approve_their_own_post(moderator, world, db):
	post_id = db("INSERT INTO posts (title, description, content_type, category, created_by, status, version_number) VALUES ('Mine', '<p>x</p>', 'Text/Article', 'General', ?, 'PENDING_APPROVAL', 1) RETURNING id", (world.users["mod"],))[0]["id"]
	response = moderator.post(f"/community/approval-queue/{post_id}/action", data={"action": "APPROVE", "comments": "self"}, follow_redirects=True)
	assert b"cannot review your own" in response.data
	assert db("SELECT status FROM posts WHERE id = ?", (post_id,))[0]["status"] == "PENDING_APPROVAL"


def test_moderators_only_see_groups_they_moderate(moderator, admin, world, db):
	other = db("INSERT INTO groups (name, description, group_type, status, created_by) VALUES ('Admin Group', '', 'team', 'active', ?) RETURNING id", (world.users["admin"],))[0]["id"]
	db("INSERT INTO group_moderators (group_id, user_id, status) VALUES (?, ?, 'Active')", (other, world.users["admin"]))
	assert moderator.get(f"/groups/{world.group_id}").status_code == 200
	assert moderator.get(f"/groups/{other}").status_code == 302
	assert admin.get(f"/groups/{other}").status_code == 200


# ---------------------------------------------------------------------------
# Batch G - hardening
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_dns(monkeypatch):
	"""example.com resolves to a public address; loopback/private names resolve to themselves."""
	import socket

	def resolve(host, port, proto=None, **kwargs):
		address = {"example.com": "93.184.216.34", "localhost": "127.0.0.1"}.get(host, host)
		return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

	monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture
def fake_fetch(monkeypatch):
	import urllib.request

	from tests.helpers import FakeHTTPResponse

	monkeypatch.setattr(urllib.request, "urlopen", lambda req, *a, **k: FakeHTTPResponse(getattr(req, "full_url", str(req))))


def test_proxy_embed_requires_login(anon, world, fake_dns, fake_fetch):
	response = anon.get("/proxy/embed?url=https://example.com/course")
	assert response.status_code == 302


def test_proxy_embed_only_serves_visible_course_urls(student, world, fake_dns, fake_fetch, db):
	assert student.get("/proxy/embed?url=https://example.com/course").status_code == 200  # assigned course
	assert student.get("/proxy/embed?url=https://example.com/not-a-course").status_code == 403
	db("UPDATE courses SET content_url = 'https://example.com/draft-only' WHERE id = ?", (world.mod_draft_course_id,))
	assert student.get("/proxy/embed?url=https://example.com/draft-only").status_code == 403  # draft, not visible


@pytest.mark.parametrize("target", ["http://127.0.0.1:5050/admin", "file:///etc/passwd", "http://169.254.169.254/latest/meta-data", "http://10.0.0.8/"])
def test_proxy_embed_refuses_unsafe_targets_even_for_course_urls(student, world, fake_dns, fake_fetch, db, target):
	db("UPDATE courses SET content_url = ? WHERE id = ?", (target, world.mod_published_course_id))
	assert student.get(f"/proxy/embed?url={target}").status_code == 403


def test_course_iframe_sandbox_does_not_grant_same_origin():
	from pathlib import Path

	html = Path(app_module.__file__).resolve().parent.joinpath("templates", "course.html").read_text(encoding="utf-8")
	assert "allow-same-origin" not in html


def test_post_attachments_with_disallowed_types_are_skipped(student, world, db):
	response = student.post(
		"/community/create",
		data={
			"title": "Attach Test", "description": "<p>x</p>", "content_type": "Text/Article", "category": "General", "status": "DRAFT",
			"attachments": [(io.BytesIO(b"<script>alert(1)</script>"), "evil.html"), (io.BytesIO(b"%PDF-1.4"), "fine.pdf")],
		},
		content_type="multipart/form-data",
		follow_redirects=True,
	)
	assert response.status_code == 200
	post_id = db("SELECT id FROM posts WHERE title = 'Attach Test'")[0]["id"]
	names = [r["file_name"] for r in db("SELECT file_name FROM post_attachments WHERE post_id = ?", (post_id,))]
	assert names == ["fine.pdf"]
	assert b"not allowed" in response.data


def test_uploads_require_login(anon, student, world):
	assert anon.get(f"/uploads/{world.upload_name}").status_code == 302
	assert student.get(f"/uploads/{world.upload_name}").status_code == 200


def test_uploads_serve_non_media_as_attachments_with_nosniff(student, world):
	(app_module.UPLOAD_FOLDER / "notes.html").write_text("<script>alert(1)</script>")
	response = student.get("/uploads/notes.html")
	assert response.status_code == 200
	assert response.headers["X-Content-Type-Options"] == "nosniff"
	assert "attachment" in response.headers.get("Content-Disposition", "")
	inline = student.get(f"/uploads/{world.upload_name}")
	assert "attachment" not in inline.headers.get("Content-Disposition", "")


def test_secret_key_is_generated_and_persisted_when_not_configured(tmp_path, monkeypatch):
	monkeypatch.delenv("LMS_SECRET_KEY", raising=False)
	monkeypatch.setenv("LMS_SECRET_KEY_FILE", str(tmp_path / ".secret_key"))
	first = app_module.create_app().secret_key
	second = app_module.create_app().secret_key
	assert first == second and first != "change-this-local-secret" and len(first) >= 64


def test_session_cookie_flags(anon, login):
	response = login(anon, "student")
	cookie = response.headers.get("Set-Cookie", "")
	assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_user_interests_require_login(anon, student, world):
	assert anon.get(f"/api/users/{world.users['maya.student']}/interests").status_code == 401
	assert student.get(f"/api/users/{world.users['student']}/interests").status_code == 200
