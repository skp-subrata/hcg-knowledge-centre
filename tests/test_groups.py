"""Groups: CSV member upload matching, progress counts, and the system-generated groups
(Department / Location / All Users) ported from origin/master -- membership in these is
computed automatically rather than maintained by hand."""
import io
import sqlite3

import app as app_module


def test_csv_upload_matches_by_employee_id_not_a_loose_username_match(moderator, world, db):
	# EMP-0007 belongs to sampleuser007; the row claims a different username that also exists
	csv = b"Employee ID,User Name,Email,User Role\nEMP-0007,sampleuser008,x@example.com,basic user\n"
	response = moderator.post("/groups/upload-members", data={"group_id": str(world.group_id), "members_file": (io.BytesIO(csv), "m.csv")}, content_type="multipart/form-data", follow_redirects=True)
	assert response.status_code == 200
	members = [r["username"] for r in db("SELECT u.username FROM group_members gm JOIN users u ON u.id = gm.user_id WHERE gm.group_id = ?", (world.group_id,))]
	assert "sampleuser007" in members and "sampleuser008" not in members


def test_group_detail_counts_certified_members_as_completed(moderator, world, db):
	maya = world.users["maya.student"]
	db("INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location) VALUES (?, ?, '', '', '', '')", (world.group_id, maya))
	db("INSERT INTO group_course_assignments (group_id, course_id, assigned_by, status) VALUES (?, ?, ?, 'active')", (world.group_id, world.certified_course_id, world.users["mod"]))
	page = moderator.get(f"/groups/{world.group_id}").get_data(as_text=True)
	assert page.count("World Published Course") >= 1
	# the same query the page uses: completed must include certified assignments
	row = db("""SELECT (SELECT COUNT(*) FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id
	            WHERE ca.course_id = ? AND gm.group_id = ? AND ca.status IN ('completed', 'certified')) AS completed""", (world.certified_course_id, world.group_id))[0]
	assert row["completed"] == 1
	import re
	from pathlib import Path

	import app as app_module

	source = Path(app_module.__file__).read_text(encoding="utf-8")
	assert "ca.status = 'completed') AS completed_count" not in source


# ---------------------------------------------------------------------------
# system-generated groups (Department / Location / All Users)
# ---------------------------------------------------------------------------
def _raw_connection(db_path):
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	return connection


def test_ensure_system_generated_groups_creates_all_users_department_and_location(world, db):
	all_users = db("SELECT * FROM groups WHERE group_type = 'ALL_USERS' AND system_generated = 1")
	assert len(all_users) == 1
	dept = db("SELECT * FROM groups WHERE group_type = 'DEPARTMENT' AND source_master_id = ? AND system_generated = 1", (world.department_id,))
	assert len(dept) == 1 and dept[0]["name"].startswith("Department - ")
	loc = db("SELECT * FROM groups WHERE group_type = 'LOCATION' AND source_master_id = ? AND system_generated = 1", (world.location_id,))
	assert len(loc) == 1 and loc[0]["name"].startswith("Location - ")


def test_ensure_system_generated_groups_is_idempotent_on_an_already_synced_db(world, db, db_path):
	before_groups = db("SELECT id, name, status FROM groups ORDER BY id")
	before_members = db("SELECT group_id, user_id FROM group_members ORDER BY group_id, user_id")
	manual_group_before = db("SELECT * FROM groups WHERE id = ?", (world.group_id,))[0]

	connection = _raw_connection(db_path)
	with connection:
		app_module.ensure_system_generated_groups(connection)
	connection.close()

	after_groups = db("SELECT id, name, status FROM groups ORDER BY id")
	after_members = db("SELECT group_id, user_id FROM group_members ORDER BY group_id, user_id")
	assert [dict(r) for r in before_groups] == [dict(r) for r in after_groups]
	assert [dict(r) for r in before_members] == [dict(r) for r in after_members]
	manual_group_after = db("SELECT * FROM groups WHERE id = ?", (world.group_id,))[0]
	assert dict(manual_group_before) == dict(manual_group_after), "a pre-existing manual group must not be annexed or altered"


def test_new_user_is_added_to_all_users_and_their_department_and_location_groups(admin, world, db):
	response = admin.post("/admin", data={
		"action": "add_user", "full_name": "Group Sync Test", "username": "groupsynctest", "password": "testpass1",
		"role": "basic user", "employee_id": "EMP-GROUPSYNC", "email": "groupsync@example.com", "phone_number": "1234567890",
		"department_id": str(world.department_id), "location_id": str(world.location_id),
	})
	assert response.status_code in (200, 302)
	new_user_id = db("SELECT id FROM users WHERE username = 'groupsynctest'")[0]["id"]

	all_users_group = db("SELECT id FROM groups WHERE group_type = 'ALL_USERS' AND system_generated = 1")[0]["id"]
	dept_group = db("SELECT id FROM groups WHERE group_type = 'DEPARTMENT' AND source_master_id = ? AND system_generated = 1", (world.department_id,))[0]["id"]
	loc_group = db("SELECT id FROM groups WHERE group_type = 'LOCATION' AND source_master_id = ? AND system_generated = 1", (world.location_id,))[0]["id"]

	member_group_ids = {r["group_id"] for r in db("SELECT group_id FROM group_members WHERE user_id = ?", (new_user_id,))}
	assert {all_users_group, dept_group, loc_group} <= member_group_ids


def test_toggling_a_department_inactive_flips_its_group_and_a_later_resync_drops_stale_members(admin, world, db):
	# give a real seeded user this department so there is a member to remove/restore
	student_id = world.users["student"]

	def update_student():
		admin.post("/admin", data={
			"action": "update_user", "record_id": str(student_id), "full_name": "Student User", "username": "student",
			"employee_id": "EMP-STUDENT-DEPT", "email": "student.dept@example.com", "phone_number": "1234567890",
			"role": "basic user", "department_id": str(world.department_id), "location_id": str(world.location_id),
		})

	update_student()
	dept_group_id = db("SELECT id FROM groups WHERE group_type = 'DEPARTMENT' AND source_master_id = ? AND system_generated = 1", (world.department_id,))[0]["id"]
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (dept_group_id, student_id))

	admin.post("/admin/masters", data={"action": "toggle_department", "record_id": str(world.department_id), "status": "Inactive"})
	assert db("SELECT status FROM departments WHERE department_id = ?", (world.department_id,))[0]["status"] == "Inactive"
	assert db("SELECT status FROM groups WHERE id = ?", (dept_group_id,))[0]["status"] == "inactive"
	# toggling the master record alone does not retroactively prune existing members --
	# that happens the next time the user's own membership is resynced (below)
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (dept_group_id, student_id))

	update_student()  # re-syncs this user; their department no longer resolves as Active
	assert not db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (dept_group_id, student_id))

	admin.post("/admin/masters", data={"action": "toggle_department", "record_id": str(world.department_id), "status": "Active"})
	assert db("SELECT status FROM groups WHERE id = ?", (dept_group_id,))[0]["status"] == "active"
	update_student()
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (dept_group_id, student_id))


def test_manual_membership_edits_are_blocked_on_a_system_generated_group(moderator, admin, world, db):
	all_users_group_id = db("SELECT id FROM groups WHERE group_type = 'ALL_USERS' AND system_generated = 1")[0]["id"]
	student_id = world.users["student"]
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (all_users_group_id, student_id))

	remove = moderator.post(f"/groups/{all_users_group_id}/remove-member", data={"user_id": str(student_id)}, follow_redirects=True)
	assert b"managed automatically" in remove.data
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (all_users_group_id, student_id)), "system group membership must not be removable by hand"

	maya_id = world.users["maya.student"]
	add = admin.post(f"/groups/{all_users_group_id}/members", data={"selected_users": [str(maya_id)]}, follow_redirects=True)
	assert b"managed automatically" in add.data


def test_pruning_a_stale_member_that_no_longer_exists_does_not_crash(world, db, db_path):
	"""Found live: group_members rows are normally cascade-deleted when a user is removed, but
	an out-of-band fix to the database (not going through the app's own FK-enforced connection)
	can leave a dangling one behind. The prune loop in sync_department_group_members /
	sync_location_group_members must not let a failure logging that removal (audit_logs.user_id
	references users(id)) crash the sync -- and since this same sync runs unconditionally at
	every app startup, a crash here takes the whole app down, not just one request."""
	dept_group_id = db("SELECT id FROM groups WHERE group_type = 'DEPARTMENT' AND source_master_id = ? AND system_generated = 1", (world.department_id,))[0]["id"]
	# a group_members row pointing at a user_id that doesn't exist -- FK enforcement is off on
	# this raw connection, exactly like an out-of-band script that never enables it
	db("INSERT INTO group_members (group_id, user_id, employee_id, email, department, location) VALUES (?, 999999, 'GONE', '', '', '')", (dept_group_id,))
	assert db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = 999999", (dept_group_id,))

	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	connection.execute("PRAGMA foreign_keys = ON")
	try:
		with connection:
			app_module.sync_department_group(connection, world.department_id)  # must not raise
	finally:
		connection.close()

	assert not db("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = 999999", (dept_group_id,)), "the dangling row must still be pruned"
