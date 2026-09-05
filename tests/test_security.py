"""Authorization and hardening: who may do what, and the SSRF / upload / cookie guards."""
import io

import pytest

import app as app_module


# ---------------------------------------------------------------------------
# Batch F - authorization
# ---------------------------------------------------------------------------
def test_moderator_cannot_generate_or_revoke_api_credentials(moderator, world, db):
	admin_id = world.users["admin"]
	before = db("SELECT id, status FROM api_credentials WHERE user_id = ?", (admin_id,))
	moderator.post("/admin", data={"action": "generate_api_creds", "target_user_id": admin_id})
	moderator.post("/admin", data={"action": "revoke_api_creds", "target_user_id": admin_id})
	after = db("SELECT id, status FROM api_credentials WHERE user_id = ?", (admin_id,))
	assert [tuple(r) for r in after] == [tuple(r) for r in before]
	assert after[0]["status"] == "active"


def test_moderator_admin_page_does_not_leak_api_secrets(moderator, world):
	page = moderator.get("/admin").get_data(as_text=True)
	assert "as_world_admin" not in page and "as_world_mod" not in page


def test_admin_page_shows_api_credentials_to_admins(admin, world):
	assert "as_world_admin" in admin.get("/admin").get_data(as_text=True)


def test_impersonating_admin_cannot_switch_role(admin, world):
	maya = world.users["maya.student"]
	assert admin.post(f"/admin/view-as/{maya}").status_code == 302
	with admin.session_transaction() as sess:
		assert sess["user_id"] == maya and sess["role"] == "basic user" and sess["impersonator_id"] == world.users["admin"]
		assert sess["actual_role"] == "basic user", "the impersonated user's real role, not the admin's"
	admin.get("/switch-role")
	with admin.session_transaction() as sess:
		assert sess["role"] == "basic user"
	assert admin.get("/admin").status_code == 302  # still locked out while impersonating


def test_exit_view_restores_the_administrator(admin, world):
	admin.post(f"/admin/view-as/{world.users['maya.student']}")
	admin.get("/admin/exit-view")
	with admin.session_transaction() as sess:
		assert sess["user_id"] == world.users["admin"]
		assert sess["role"] == "admin" and sess["actual_role"] == "admin"
		assert "impersonator_id" not in sess
	assert admin.get("/admin").status_code == 200


def test_inactive_user_cannot_log_in(anon, world, db, login):
	db("UPDATE users SET is_active = 0 WHERE username = 'student'")
	response = login(anon, "student")
	assert response.status_code == 200 and b"Invalid username or password" in response.data
	with anon.session_transaction() as sess:
		assert "user_id" not in sess


def test_reviewer_cannot_approve_their_own_post(moderator, world, db):
	post_id = db("INSERT INTO posts (title, description, content_type, category, created_by, status, version_number) VALUES ('Mine', '<p>x</p>', 'Text/Article', 'General', ?, 'PENDING_APPROVAL', 1) RETURNING id", (world.users["mod"],))[0]["id"]
	response = moderator.post(f"/community/approval-queue/{post_id}/action", data={"action": "APPROVE", "comments": "self"}, follow_redirects=True)
	assert b"cannot review your own" in response.data
	assert db("SELECT status FROM posts WHERE id = ?", (post_id,))[0]["status"] == "PENDING_APPROVAL"


def test_moderators_only_see_groups_they_moderate(moderator, admin, world, db):
	other = db("INSERT INTO groups (name, description, group_type, status, created_by) VALUES ('Admin Group', '', 'team', 'active', ?) RETURNING id", (world.users["admin"],))[0]["id"]
	db("INSERT INTO group_moderators (group_id, user_id, status) VALUES (?, ?, 'Active')", (other, world.users["admin"]))
	assert moderator.get(f"/groups/{world.group_id}").status_code == 200
	assert moderator.get(f"/groups/{other}").status_code == 302
	assert admin.get(f"/groups/{other}").status_code == 200
