"""API v1 with header authentication only - no browser session involved."""
import pytest


def test_leaderboard_reads_user_wallets(anon, world):
	response = anon.get("/api/v1/leaderboard", headers=world.api_keys["student"])
	assert response.status_code == 200, response.get_data(as_text=True)[:200]
	usernames = [row["username"] for row in response.get_json()["leaderboard"]]
	assert "maya.student" in usernames


def test_comment_post_writes_comment_text(anon, world, db):
	response = anon.post(
		f"/api/v1/posts/{world.published_post_id}/comment",
		json={"comment": "via api"},
		headers=world.api_keys["student"],
	)
	assert response.status_code == 201, response.get_json()
	rows = db("SELECT comment_text FROM post_comments WHERE post_id = ? AND comment_text = 'via api'", (world.published_post_id,))
	assert len(rows) == 1


def test_get_course_with_api_key_only(anon, world):
	response = anon.get(f"/api/v1/courses/{world.python_course_id}", headers=world.api_keys["student"])
	assert response.status_code == 200, response.get_data(as_text=True)[:200]
	assert response.get_json()["course"]["name"] == "Python Foundations"


def test_assign_course_with_api_key_only(anon, world, db):
	response = anon.post(
		f"/api/v1/courses/{world.python_course_id}/assign",
		json={"student_id": world.users["student"]},
		headers=world.api_keys["mod"],
	)
	assert response.status_code == 200, response.get_data(as_text=True)[:200]
	assert db("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (world.python_course_id, world.users["student"]))


@pytest.mark.parametrize("path", ["/api/v1/departments", "/api/v1/positions", "/api/v1/locations"])
def test_masters_can_be_added_with_an_api_key(anon, world, path):
	response = anon.post(path, json={"name": f"Smoke {path.rsplit('/', 1)[1]}"}, headers=world.api_keys["admin"])
	assert response.status_code == 201, response.get_data(as_text=True)[:200]


def test_masters_can_be_added_from_a_staff_session(admin, world):
	response = admin.post("/api/v1/departments", json={"name": "Session Department"})
	assert response.status_code == 201, response.get_data(as_text=True)[:200]


def test_masters_reject_a_student_session_without_api_key(student, world):
	assert student.post("/api/v1/departments", json={"name": "Nope"}).status_code == 401


def test_api_interests_post_requires_login(anon, student, world):
	assert anon.post("/api/interests", json={"interest_name": "Anon Interest"}).status_code == 401
	assert student.post("/api/interests", json={"interest_name": "Student Interest"}).status_code == 201


def test_admin_page_add_master_targets_real_endpoints():
	"""admin.html's addMaster() must call /api/interests for interests; /api/v1/interests does not exist."""
	from pathlib import Path

	html = Path(__file__).resolve().parents[1].joinpath("templates", "admin.html").read_text(encoding="utf-8")
	assert "/api/v1/interests" not in html
	assert "'/api/interests'" in html and "interest_name" in html


# ---------------------------------------------------------------------------
# Batch B - API semantics
# ---------------------------------------------------------------------------
def test_create_course_stores_status_lowercase(anon, world, db):
	response = anon.post(
		"/api/v1/courses",
		json={"name": "Case Course", "content_type": "URL", "content_url": "https://example.com/c", "status": "PUBLISHED"},
		headers=world.api_keys["mod"],
	)
	assert response.status_code == 201, response.get_json()
	assert db("SELECT status FROM courses WHERE id = ?", (response.get_json()["course_id"],))[0]["status"] == "published"


def test_uppercase_status_rows_still_count_as_published(anon, admin, world, db):
	"""Rows written by the old API path are upper-case; every reader must treat them as published."""
	db("INSERT INTO courses (name, description, category, content_type, content_url, created_by, status) "
	   "VALUES ('Legacy Upper Course', '', 'General', 'URL', 'https://example.com/legacy', ?, 'PUBLISHED')", (world.users["mod"],))
	listing = anon.get("/api/v1/courses", headers=world.api_keys["student"]).get_json()
	assert "Legacy Upper Course" in [c["name"] for c in listing["courses"]]
	admin_page = admin.get("/admin").get_data(as_text=True)
	assert "Legacy Upper Course" in admin_page  # the assign-course dropdown


def test_get_post_hides_unpublished_posts_from_other_users(anon, world, api_headers):
	other = api_headers("maya.student")
	assert anon.get(f"/api/v1/posts/{world.draft_post_id}", headers=other).status_code == 403
	assert anon.get(f"/api/v1/posts/{world.draft_post_id}", headers=world.api_keys["student"]).status_code == 200  # author
	assert anon.get(f"/api/v1/posts/{world.draft_post_id}", headers=world.api_keys["mod"]).status_code == 200  # staff
	assert anon.get(f"/api/v1/posts/{world.published_post_id}", headers=other).status_code == 200


def test_comment_post_rejects_unpublished_posts_for_other_users(anon, world, api_headers):
	other = api_headers("maya.student")
	response = anon.post(f"/api/v1/posts/{world.draft_post_id}/comment", json={"comment": "peeking"}, headers=other)
	assert response.status_code == 403


def test_create_user_lowercases_username_so_login_works(anon, world, db, login):
	response = anon.post(
		"/api/v1/users",
		json={"username": "Mixed.Case", "full_name": "Mixed Case", "password": "secret123", "role": "basic user"},
		headers=world.api_keys["admin"],
	)
	assert response.status_code == 201, response.get_json()
	assert db("SELECT username FROM users WHERE full_name = 'Mixed Case'")[0]["username"] == "mixed.case"
	assert login(anon, "Mixed.Case", "secret123").status_code == 302
	with anon.session_transaction() as sess:
		assert sess.get("user_id")


def test_inactive_user_api_key_is_rejected(anon, world, db):
	db("UPDATE users SET is_active = 0 WHERE id = ?", (world.users["student"],))
	response = anon.get("/api/v1/courses", headers=world.api_keys["student"])
	assert response.status_code == 401
