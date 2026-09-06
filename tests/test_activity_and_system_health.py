"""Activity log (logins, page views, a bounded set of business events) and the System health
page (CPU/disk/memory, sampled when the page is viewed) added for the admin System & activity
workspace."""
import json
import sqlite3

import pytest

import app as app_module


def _events(db, event_type=None):
	if event_type:
		return db("SELECT * FROM activity_log WHERE event_type = ? ORDER BY id", (event_type,))
	return db("SELECT * FROM activity_log ORDER BY id")


# ---------------------------------------------------------------------------
# log_activity(): the low-level writer, and its auto-prune
# ---------------------------------------------------------------------------
def test_log_activity_writes_a_row_with_json_details(db_path, db):
	connection = sqlite3.connect(db_path)
	with connection:
		app_module.log_activity(connection, 1, "login_success", {"username": "admin"})
	connection.close()
	rows = _events(db, "login_success")
	assert len(rows) == 1
	assert rows[0]["user_id"] == 1
	assert json.loads(rows[0]["details"]) == {"username": "admin"}


def test_log_activity_accepts_no_details():
	connection = sqlite3.connect(":memory:")
	connection.execute("CREATE TABLE activity_log (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, event_type TEXT, details TEXT)")
	with connection:
		app_module.log_activity(connection, None, "logout")
	row = connection.execute("SELECT * FROM activity_log").fetchone()
	assert row[3] == "logout" and json.loads(row[4]) == {}


def test_log_activity_prunes_rows_older_than_the_retention_window(db_path, db):
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	with connection:
		connection.execute(
			"INSERT INTO activity_log (user_id, event_type, details, created_at) VALUES (1, 'page_view', '{}', datetime('now', '-200 days'))"
		)
		app_module.log_activity(connection, 1, "page_view", {"path": "/"})
	connection.close()
	rows = _events(db)
	assert len(rows) == 1  # the 200-day-old row was pruned; only the fresh one remains
	assert rows[0]["event_type"] == "page_view"


# ---------------------------------------------------------------------------
# Instrumented routes actually write the expected event
# ---------------------------------------------------------------------------
def test_successful_login_is_logged(anon, login, db):
	login(anon, "admin")
	rows = _events(db, "login_success")
	assert len(rows) == 1 and json.loads(rows[0]["details"])["username"] == "admin"


def test_failed_login_is_logged_with_the_attempted_username(anon, login, db):
	login(anon, "admin", password="wrong-password")
	rows = _events(db, "login_failure")
	assert len(rows) == 1 and json.loads(rows[0]["details"])["username"] == "admin"


def test_logout_is_logged_for_a_signed_in_user(student, db):
	token_page = student.get("/profile").get_data(as_text=True)
	import re
	token = re.search(r'name="csrf_token" value="([^"]*)"', token_page)
	student.post("/logout", data={"csrf_token": token.group(1)} if token else {})
	rows = _events(db, "logout")
	assert len(rows) == 1


def test_page_view_is_logged_for_a_real_page(student, db):
	student.get("/profile")
	rows = [r for r in _events(db, "page_view") if json.loads(r["details"])["path"] == "/profile"]
	assert len(rows) == 1


def test_page_view_is_not_logged_for_json_api_endpoints(student, db):
	student.get("/api/notifications/unread")
	assert _events(db, "page_view") == []


def test_page_view_is_not_logged_for_static_assets(student, db):
	student.get("/static/css/app.css")
	assert _events(db, "page_view") == []


def test_post_created_is_logged(student, db):
	student.post("/community/create", data={
		"title": "Activity log test post", "description": "<p>d</p>", "content_type": "Text/Article", "category": "General", "topic_tag": "t",
	})
	rows = _events(db, "post_created")
	assert len(rows) == 1 and json.loads(rows[0]["details"])["title"] == "Activity log test post"


def test_post_reviewed_is_logged(moderator, world, db):
	response = moderator.post(f"/community/approval-queue/{world.pending_post_id}/action", data={"action": "APPROVE"})
	assert response.status_code in (200, 302)
	rows = _events(db, "post_reviewed")
	assert len(rows) == 1 and json.loads(rows[0]["details"])["action"] == "APPROVE"


def test_assessment_submission_is_logged(student, world, db_path, db):
	from tests.helpers import make_assessment
	assessment_id, qids = make_assessment(db_path, world.mod_published_course_id, questions=(("Q", "a", 1),))
	student.post(f"/assessments/{assessment_id}", data={f"q{qids[0]}": "a"})
	rows = _events(db, "assessment_submitted")
	assert len(rows) == 1
	details = json.loads(rows[0]["details"])
	assert details["assessment_id"] == assessment_id and details["result"] == "pass"


def test_course_certified_is_logged_exactly_once(db_path, db, world):
	rohan = world.users["rohan.student"]
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	with connection:
		app_module.issue_certificate(connection, rohan, world.mod_published_course_id)
		app_module.issue_certificate(connection, rohan, world.mod_published_course_id)  # idempotent re-call must not log twice
	connection.close()
	rows = _events(db, "course_certified")
	assert len(rows) == 1 and json.loads(rows[0]["details"])["course_id"] == world.mod_published_course_id


# ---------------------------------------------------------------------------
# record_system_snapshot(): degrades gracefully, never raises
# ---------------------------------------------------------------------------
def test_snapshot_without_pythonanywhere_env_vars_has_no_cpu_figures(db_path, db, monkeypatch):
	monkeypatch.delenv("PYTHONANYWHERE_USERNAME", raising=False)
	monkeypatch.delenv("PYTHONANYWHERE_API_TOKEN", raising=False)
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	with connection:
		snapshot = app_module.record_system_snapshot(connection)
	connection.close()
	assert snapshot["cpu_used_seconds"] is None and snapshot["cpu_limit_seconds"] is None
	assert snapshot["disk_quota_bytes"] is None  # no fixed quota known off PythonAnywhere
	assert snapshot["disk_used_bytes"] is not None  # still measures the app's own directory
	assert snapshot["healthy"] is True


def test_snapshot_records_a_history_row(db_path, db, monkeypatch):
	monkeypatch.delenv("PYTHONANYWHERE_USERNAME", raising=False)
	connection = sqlite3.connect(db_path)
	with connection:
		app_module.record_system_snapshot(connection)
	connection.close()
	assert db("SELECT COUNT(*) AS n FROM system_metric_snapshots")[0]["n"] == 1


def test_snapshot_never_raises_even_if_the_pythonanywhere_api_call_is_blocked(db_path, db, monkeypatch):
	"""The no_network test fixture blocks requests.sessions.Session.request; with both env
	vars set this exercises the real call path, proving the broad except clause holds."""
	monkeypatch.setenv("PYTHONANYWHERE_USERNAME", "someuser")
	monkeypatch.setenv("PYTHONANYWHERE_API_TOKEN", "sometoken")
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	with connection:
		snapshot = app_module.record_system_snapshot(connection)  # must not raise
	connection.close()
	assert snapshot["cpu_used_seconds"] is None  # the blocked call left it unset, not an error


# ---------------------------------------------------------------------------
# _directory_size_bytes() / format_bytes()
# ---------------------------------------------------------------------------
def test_directory_size_bytes_sums_a_small_tree(tmp_path):
	(tmp_path / "a.txt").write_text("12345")
	nested = tmp_path / "nested"
	nested.mkdir()
	(nested / "b.txt").write_text("1234567890")
	assert app_module._directory_size_bytes(tmp_path) == 15


@pytest.mark.parametrize("value,expected", [
	(None, None),
	(0, "0 B"),
	(512, "512 B"),
	(2048, "2.0 KB"),
	(5 * 1024 * 1024, "5.0 MB"),
	(3 * 1024 * 1024 * 1024, "3.0 GB"),
])
def test_format_bytes(value, expected):
	assert app_module.format_bytes(value) == expected


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------
def test_system_page_is_admin_only(student, moderator, admin):
	assert student.get("/admin/system").status_code == 302
	assert moderator.get("/admin/system").status_code == 302
	assert admin.get("/admin/system").status_code == 200


def test_system_page_paginates_the_activity_log(db_path, db, admin):
	connection = sqlite3.connect(db_path)
	with connection:
		for i in range(30):
			app_module.log_activity(connection, None, "page_view", {"path": f"/x{i}"})
	connection.close()
	first_page = admin.get("/admin/system").get_data(as_text=True)
	assert "Page 1 of" in first_page
	second_page = admin.get("/admin/system?page=2").get_data(as_text=True)
	assert "Page 2 of" in second_page
