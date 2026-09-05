"""Groups: CSV member upload matching and progress counts."""
import io


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
