"""Login, role switching and the two dashboards render."""
import pytest

import app as app_module


def test_home_anonymous_shows_login_form(anon):
	response = anon.get("/")
	assert response.status_code == 200
	assert b'name="username"' in response.data and b'name="password"' in response.data


@pytest.mark.parametrize(
	"username, expected_actual_role",
	[("admin", "admin"), ("mod", "moderator"), ("student", "basic user")],
)
def test_login_always_starts_as_basic_user(anon, login, username, expected_actual_role):
	response = login(anon, username)
	assert response.status_code == 302
	with anon.session_transaction() as sess:
		assert sess["role"] == "basic user"
		assert sess["actual_role"] == expected_actual_role
		assert sess["user_id"]


def test_wrong_password_is_rejected(anon, login):
	response = login(anon, "admin", "not-the-password")
	assert response.status_code == 200
	assert b"Invalid username or password" in response.data
	with anon.session_transaction() as sess:
		assert "user_id" not in sess


def test_switch_role_toggles_for_staff(anon, login):
	login(anon, "admin")
	anon.get("/switch-role")
	with anon.session_transaction() as sess:
		assert sess["role"] == "admin"
	anon.get("/switch-role")
	with anon.session_transaction() as sess:
		assert sess["role"] == "basic user"


def test_switch_role_is_refused_for_students(anon, login):
	login(anon, "student")
	response = anon.get("/switch-role", follow_redirects=True)
	assert b"Only staff members can switch roles" in response.data
	with anon.session_transaction() as sess:
		assert sess["role"] == "basic user"


def test_admin_panel_needs_the_switch(anon, login):
	login(anon, "admin")
	assert anon.get("/admin").status_code == 302
	anon.get("/switch-role")
	response = anon.get("/admin")
	assert response.status_code == 200


def test_student_dashboard_renders(student):
	response = student.get("/")
	assert response.status_code == 200
	assert b"Welcome back" in response.data


def test_moderator_and_admin_pages_render(moderator, admin):
	assert moderator.get("/courses").status_code == 200
	assert admin.get("/admin/masters").status_code == 200
	assert admin.get("/admin/reports").status_code == 200


def test_no_duplicate_url_rules():
	seen = {}
	for rule in app_module.app.url_map.iter_rules():
		for method in rule.methods - {"HEAD", "OPTIONS"}:
			key = (rule.rule, method)
			assert key not in seen, f"{key} is registered by both {seen[key]} and {rule.endpoint}"
			seen[key] = rule.endpoint
