"""Admin panel, deletion, docs page and template/route consistency."""
import re
from pathlib import Path

from flask import template_rendered

import app as app_module

ROOT = Path(app_module.__file__).resolve().parent


def test_search_assignable_students_only_returns_basic_users(admin, moderator, student, anon, world, db):
	# the moderator's own username ('mod') must never appear even though it matches 'mod'
	response = admin.get("/api/admin/students/search?q=mod")
	assert response.status_code == 200
	names = {row["username"] for row in response.get_json()["data"]}
	assert "mod" not in names

	# a real basic-user account is found by a fragment of their username
	target = db("SELECT username FROM users WHERE role = 'basic user' LIMIT 1")[0]["username"]
	fragment = target[:4]
	found = {row["username"] for row in admin.get(f"/api/admin/students/search?q={fragment}").get_json()["data"]}
	assert target in found

	# a moderator (not just an admin) can use this picker too -- the "Assign a course" form
	# is available to both
	assert moderator.get("/api/admin/students/search?q=").status_code == 200

	assert student.get("/api/admin/students/search?q=a").status_code in (302, 403)
	assert anon.get("/api/admin/students/search?q=a").status_code in (302, 403)


def test_delete_record_with_an_unknown_resource_redirects(admin, world):
	response = admin.post("/admin/delete/module/1")
	assert response.status_code == 302
	followed = admin.post("/admin/delete/module/1", follow_redirects=True)
	assert b"cannot be deleted" in followed.data


def test_delete_record_ignores_a_foreign_referrer(admin, world):
	response = admin.post(f"/admin/delete/course/{world.mod_draft_course_id}", headers={"Referer": "https://evil.example/steal"})
	assert response.status_code == 302
	assert "evil.example" not in response.headers["Location"]


def test_add_user_persists_interests(admin, world, db):
	response = admin.post("/admin", data={
		"action": "add_user", "full_name": "Interested Person", "username": "interested.person", "password": "secret123",
		"role": "basic user", "employee_id": "EMP-INT", "email": "interested@example.com", "phone_number": "1234567890",
		"location_id": world.location_id, "department_id": world.department_id, "interests": [str(world.interest_id)],
	})
	assert response.status_code in (200, 302)
	user_id = db("SELECT id FROM users WHERE username = 'interested.person'")[0]["id"]
	assert [r["interest_id"] for r in db("SELECT interest_id FROM user_interest WHERE user_id = ?", (user_id,))] == [world.interest_id]


def test_update_user_persists_interests(admin, world, db):
	second = db("SELECT id FROM interest_master ORDER BY id LIMIT 1 OFFSET 1")[0]["id"]
	uid = world.users["student"]
	response = admin.post("/admin", data={
		"action": "update_user", "record_id": uid, "full_name": "Student", "username": "student", "role": "basic user",
		"employee_id": "EMP-STUDENT", "email": "student@example.com", "phone_number": "1234567890",
		"location_id": world.location_id, "interests": [str(second)],
	})
	assert response.status_code in (200, 302)
	assert [r["interest_id"] for r in db("SELECT interest_id FROM user_interest WHERE user_id = ?", (uid,))] == [second]


def test_admin_assessments_csv_link_targets_a_real_route():
	html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
	assert "download-questions" not in html
	assert re.search(r"/assessments/\$\{[a-z]+\.id\}/questions/download", html), "JS rows must link to the questions download route"
	assert "/assessments/{{ item.id }}/questions/download" in html, "server-rendered rows must link to the questions download route"


def test_api_docs_only_lists_endpoints_that_exist():
	html = (ROOT / "templates" / "api_docs.html").read_text(encoding="utf-8")
	documented = re.findall(r'(?:render_)?api_card\("(GET|POST|PUT|DELETE)",\s*"([^"]+)"', html)
	assert documented
	rules = [(m, r.rule) for r in app_module.app.url_map.iter_rules() for m in r.methods]
	for method, path in documented:
		pattern = "^" + re.sub(r"\{(\w+)\}", r"<int:\1>", path) + "$"
		assert any(m == method and re.match(pattern, rule) for m, rule in rules), f"documented but missing: {method} {path}"


def test_every_real_api_v1_endpoint_is_documented():
	"""The reverse of test_api_docs_only_lists_endpoints_that_exist(): every real /api/v1/*
	route (the X-API-Key/X-API-Secret developer surface) must have a card in api_docs.html, so a
	new endpoint can't silently ship undocumented. Deliberately scoped to /api/v1/* only -- the
	session/staff-only AJAX helpers under /api/admin/* and /api/support/* use a different auth
	model (browser session, not an API key) and were never meant to be part of this doc."""
	html = (ROOT / "templates" / "api_docs.html").read_text(encoding="utf-8")
	documented = {
		(method, "^" + re.sub(r"\{(\w+)\}", r"<int:\1>", path) + "$")
		for method, path in re.findall(r'(?:render_)?api_card\("(GET|POST|PUT|DELETE)",\s*"([^"]+)"', html)
	}
	undocumented = []
	for rule in app_module.app.url_map.iter_rules():
		if not rule.rule.startswith("/api/v1/") or rule.rule == "/api/v1/docs":
			continue
		for method in rule.methods & {"GET", "POST", "PUT", "DELETE"}:
			if not any(method == m and re.match(pattern, rule.rule) for m, pattern in documented):
				undocumented.append(f"{method} {rule.rule}")
	assert not undocumented, f"real /api/v1 endpoints missing a card in api_docs.html: {undocumented}"


def test_context_processor_provides_only_the_active_release(student, world):
	captured = []

	def record(sender, template, context, **extra):
		captured.append(context)

	template_rendered.connect(record, app_module.app)
	try:
		assert student.get("/notifications").status_code == 200
	finally:
		template_rendered.disconnect(record, app_module.app)
	context = captured[-1]
	assert "releases" not in context
	assert context["active_release"]["version_number"]
	assert "unread_notifications_count" in context


def test_fromjson_filter_parses_release_note_lists():
	fromjson = app_module.app.jinja_env.filters["fromjson"]
	assert fromjson('["a", "b"]') == ["a", "b"]
	assert fromjson("not json") == []
	assert fromjson(None) == []


def test_admin_assessments_api_returns_pass_mark_and_attempts(admin, world):
	"""The admin table re-renders from this endpoint; without these columns the rows and the edit sheet show blanks."""
	data = admin.get("/api/admin/assessments?page=1&pageSize=5").get_json()["data"]
	assert data, "seed has assessments"
	for row in data:
		assert {"id", "title", "type", "course_name", "pass_percentage", "max_attempts"} <= set(row)
