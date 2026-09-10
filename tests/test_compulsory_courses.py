"""Compulsory courses: auto-assignment to everyone and to newly onboarded users.

Ported from origin/master alongside the system-generated groups (see test_groups.py) --
a published, is_compulsory course is assigned to every active user, and to every user
created or resynced afterward, via assign_compulsory_course_to_all/
assign_compulsory_courses_to_user in app.py.
"""
import sqlite3

import app as app_module


def _raw_connection(db_path):
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	return connection


def test_assign_compulsory_course_to_all_assigns_every_active_user_once(world, db, db_path):
	connection = _raw_connection(db_path)
	with connection:
		app_module.assign_compulsory_course_to_all(connection, world.compulsory_course_id)
	connection.close()

	student_id = world.users["student"]
	assert db("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (world.compulsory_course_id, student_id))
	notifs = db("SELECT * FROM notifications WHERE user_id = ? AND message LIKE '%compulsory course%'", (student_id,))
	assert len(notifs) == 1

	# calling it again must not duplicate assignments or notifications
	connection = _raw_connection(db_path)
	with connection:
		app_module.assign_compulsory_course_to_all(connection, world.compulsory_course_id)
	connection.close()
	assert len(db("SELECT * FROM course_assignments WHERE course_id = ? AND student_id = ?", (world.compulsory_course_id, student_id))) == 1
	assert len(db("SELECT * FROM notifications WHERE user_id = ? AND message LIKE '%compulsory course%'", (student_id,))) == 1


def test_assign_compulsory_course_to_all_skips_non_compulsory_and_unpublished_courses(world, db, db_path):
	connection = _raw_connection(db_path)
	with connection:
		app_module.assign_compulsory_course_to_all(connection, world.mod_draft_course_id)  # not compulsory
	connection.close()
	assert not db("SELECT 1 FROM course_assignments WHERE course_id = ?", (world.mod_draft_course_id,))


def test_new_user_is_auto_assigned_every_current_compulsory_course(admin, world, db):
	response = admin.post("/admin", data={
		"action": "add_user", "full_name": "Compulsory Test", "username": "compulsorytest", "password": "testpass1",
		"role": "basic user", "employee_id": "EMP-COMPULSORY", "email": "compulsory@example.com", "phone_number": "1234567890",
		"location_id": str(world.location_id),
	})
	assert response.status_code in (200, 302)
	new_user_id = db("SELECT id FROM users WHERE username = 'compulsorytest'")[0]["id"]
	assert db("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (world.compulsory_course_id, new_user_id))
	assert db("SELECT 1 FROM notifications WHERE user_id = ? AND message LIKE '%compulsory course%'", (new_user_id,))


def test_admin_marking_a_course_compulsory_on_publish_assigns_everyone(admin, world, db):
	response = admin.post("/courses/create", data={
		"name": "Newly Compulsory", "status": "published", "source_type": "url",
		"content_url": "https://example.com/new", "is_compulsory": "1",
	}, follow_redirects=True)
	assert response.status_code == 200
	course_id = db("SELECT id FROM courses WHERE name = 'Newly Compulsory'")[0]["id"]
	assert db("SELECT is_compulsory FROM courses WHERE id = ?", (course_id,))[0]["is_compulsory"] == 1
	assert db("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, world.users["student"]))


def test_moderator_cannot_set_is_compulsory_when_creating_a_course(moderator, world, db):
	moderator.post("/courses/create", data={
		"name": "Mod Cannot Compel", "status": "published", "source_type": "url",
		"content_url": "https://example.com/nope", "is_compulsory": "1",
	})
	row = db("SELECT is_compulsory FROM courses WHERE name = 'Mod Cannot Compel'")
	assert row and row[0]["is_compulsory"] == 0


def test_courses_update_preserves_is_compulsory_for_a_non_admin_owner(moderator, world, db):
	# world.compulsory_course_id is owned by 'mod' and already compulsory
	response = moderator.post(f"/courses/{world.compulsory_course_id}/update", data={
		"name": "World Compulsory Course (renamed)", "status": "published", "source_type": "url",
		"content_url": "https://example.com/compulsory", "is_compulsory": "",  # a non-admin can't uncheck it either
	}, follow_redirects=True)
	assert response.status_code == 200
	assert db("SELECT is_compulsory FROM courses WHERE id = ?", (world.compulsory_course_id,))[0]["is_compulsory"] == 1


def test_publishing_a_draft_compulsory_course_assigns_everyone(admin, world, db):
	db("UPDATE courses SET content_url = 'https://example.com/draft-only' WHERE id = ?", (world.mod_draft_course_id,))
	admin.post("/admin", data={
		"action": "update_course", "record_id": str(world.mod_draft_course_id), "name": "World Draft Course",
		"category": "Testing", "status": "draft", "is_compulsory": "1",
	})
	assert db("SELECT is_compulsory FROM courses WHERE id = ?", (world.mod_draft_course_id,))[0]["is_compulsory"] == 1
	assert not db("SELECT 1 FROM course_assignments WHERE course_id = ?", (world.mod_draft_course_id,)), "must not assign while still a draft"

	admin.post(f"/courses/{world.mod_draft_course_id}/publish")
	assert db("SELECT status FROM courses WHERE id = ?", (world.mod_draft_course_id,))[0]["status"] == "published"
	assert db("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (world.mod_draft_course_id, world.users["student"]))
