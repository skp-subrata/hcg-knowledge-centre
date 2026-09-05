"""Form input that used to crash with a 500 now fails gracefully."""
import io

import pytest

from tests.helpers import make_assessment


def test_course_duration_that_is_not_a_number_is_treated_as_zero(moderator, world, db):
	response = moderator.post("/courses/create", data={"name": "Dur Course", "status": "draft", "source_type": "url", "content_url": "", "duration_minutes": "abc", "category": "General", "difficulty": "beginner"})
	assert response.status_code == 302
	assert db("SELECT duration_minutes FROM courses WHERE name = 'Dur Course'")[0]["duration_minutes"] == 0


def test_reward_source_update_rejects_unknown_enums(admin, world, db):
	before = dict(db("SELECT * FROM reward_sources WHERE name = 'RATING_GIVEN'")[0])
	response = admin.post("/admin/rewards/source/update", data={"name": "RATING_GIVEN", "status": "Active", "calculation_type": "BOGUS", "multiplier": "1", "fixed_points": "2"}, follow_redirects=True)
	assert response.status_code == 200 and b"Invalid status or calculation type" in response.data
	assert dict(db("SELECT * FROM reward_sources WHERE name = 'RATING_GIVEN'")[0]) == before


def test_api_credentials_with_a_bad_target_user_flash_instead_of_crashing(admin, world):
	response = admin.post("/admin", data={"action": "generate_api_creds", "target_user_id": "abc"}, follow_redirects=True)
	assert response.status_code == 200 and b"Select a user" in response.data


def test_assessment_without_questions_cannot_be_submitted(student, world, db, db_path):
	assessment_id, _ = make_assessment(db_path, world.mod_published_course_id, questions=())
	response = student.post(f"/assessments/{assessment_id}", data={}, follow_redirects=True)
	assert b"no questions" in response.data
	assert not db("SELECT 1 FROM assessment_attempts WHERE assessment_id = ?", (assessment_id,))


def test_question_import_does_not_duplicate_identical_rows(admin, world, db):
	from openpyxl import Workbook

	import app as app_module

	def workbook():
		wb = Workbook(); ws = wb.active
		ws.append(list(app_module.QUESTION_COLUMNS))
		ws.append([world.mod_published_course_id, "World Published Course", "Import Test", "post", "What is 1+1?", "1", "2", "3", "4", "b", 1, "easy", "math", ""])
		buffer = io.BytesIO(); wb.save(buffer); buffer.seek(0)
		return buffer

	for _ in range(2):
		response = admin.post("/admin", data={"action": "import_questions", "question_file": (workbook(), "q.xlsx")}, content_type="multipart/form-data")
		assert response.status_code in (200, 302)
	assert db("SELECT COUNT(*) AS n FROM questions WHERE question_text = 'What is 1+1?'")[0]["n"] == 1


def test_profile_picture_is_not_saved_when_the_form_is_invalid(student, world):
	import app as app_module

	before = {p.name for p in app_module.UPLOAD_FOLDER.iterdir()}
	response = student.post("/profile", data={"full_name": "", "email": "", "phone_number": "", "employee_id": "", "profile_picture": (io.BytesIO(b"\x89PNG"), "me.png")}, content_type="multipart/form-data", follow_redirects=True)
	assert b"mandatory" in response.data
	assert {p.name for p in app_module.UPLOAD_FOLDER.iterdir()} == before
	response = student.post("/profile", data={"full_name": "S", "email": "s@example.com", "phone_number": "1", "employee_id": "EMP-S", "location_id": world.location_id, "profile_picture": (io.BytesIO(b"x"), "me.exe")}, content_type="multipart/form-data", follow_redirects=True)
	assert b"PNG, JPG, GIF or WebP" in response.data


def test_dashboard_offers_assessments_for_courses_in_progress(student, world, db_path):
	"""The dashboard query filtered on a status nothing ever writes ('completed'), so it was always empty."""
	from flask import template_rendered

	import app as app_module

	make_assessment(db_path, world.mod_published_course_id, title="Dashboard Visible Assessment")
	captured = []

	def record(sender, template, context, **extra):
		captured.append((template.name, context))

	template_rendered.connect(record, app_module.app)
	try:
		assert student.get("/").status_code == 200
	finally:
		template_rendered.disconnect(record, app_module.app)
	context = next(ctx for name, ctx in captured if name == "index.html")
	titles = [row["title"] for row in context["assessments"]]
	assert "Dashboard Visible Assessment" in titles


def test_top_learners_only_counts_certified_records(admin, world, db):
	db("INSERT INTO course_certifications (user_id, course_id, user_name, course_name, certification_status, badge) VALUES (?, ?, 'Rohan Student', 'Python Foundations', 'ASSESSMENT_FAILED', 'NOT CERTIFIED')", (world.users["rohan.student"], world.python_course_id))
	page = admin.get("/admin/reports").get_data(as_text=True)
	assert "Rohan Student" not in page
