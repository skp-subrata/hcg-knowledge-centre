"""Admin panel, deletion, docs page and template/route consistency."""
import re
from pathlib import Path

from flask import template_rendered

import app as app_module

ROOT = Path(app_module.__file__).resolve().parent


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
