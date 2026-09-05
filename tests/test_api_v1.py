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
