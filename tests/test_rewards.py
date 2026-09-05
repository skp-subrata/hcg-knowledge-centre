"""Reward engine and the two (web + API) reward-admin surfaces share one ledger convention."""
import re
from pathlib import Path

import pytest

import app as app_module


def _wallet(db, user_id):
	rows = db("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
	return dict(rows[0]) if rows else None


def _ledger_sum(db, user_id):
	return db("SELECT COALESCE(SUM(points), 0) AS total FROM reward_transactions WHERE user_id = ?", (user_id,))[0]["total"]


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
def _fire(db_path, **kwargs):
	with app_module.get_db() as connection:
		return app_module.process_reward_event(connection, **kwargs)


def test_fixed_source_pays_once_per_reference(db, db_path, world):
	uid = world.users["student"]
	args = dict(user_id=uid, event_name="RATING_GIVEN", source_reference_id="PRATE-1-1", source_reference_type="post", description="t")
	assert _fire(db_path, **args) == 2
	assert _fire(db_path, **args) == 0
	assert _wallet(db, uid)["current_balance"] == 2
	assert _ledger_sum(db, uid) == 2


def test_multiplier_source_pays_the_delta_and_lowers_total_earned_on_reversal(db, db_path, world):
	uid = world.users["student"]
	args = dict(user_id=uid, event_name="COMMUNITY_POST_RATING", source_reference_id="PRATE-9-9", source_reference_type="post", description="t")
	assert _fire(db_path, input_value=5, **args) == 5
	assert _fire(db_path, input_value=2, **args) == -3  # rating lowered -> REVERSAL
	types = [r["transaction_type"] for r in db("SELECT transaction_type FROM reward_transactions WHERE user_id = ? ORDER BY id", (uid,))]
	assert types == ["EARN", "REVERSAL"]
	wallet = _wallet(db, uid)
	assert wallet["current_balance"] == 2
	assert wallet["total_earned"] == 2, "total_earned must follow the net points from reward sources"
	assert _ledger_sum(db, uid) == 2


def test_inactive_or_unknown_source_pays_nothing(db, db_path, world):
	uid = world.users["student"]
	db("UPDATE reward_sources SET status = 'inactive' WHERE name = 'RATING_GIVEN'")
	assert _fire(db_path, user_id=uid, event_name="RATING_GIVEN", source_reference_id="x", source_reference_type="post", description="t") == 0
	assert _fire(db_path, user_id=uid, event_name="NO_SUCH_SOURCE", source_reference_id="x", source_reference_type="post", description="t") == 0
	assert _wallet(db, uid) is None


def test_every_reward_event_name_in_the_code_is_a_seeded_source(db):
	source = Path(app_module.__file__).read_text(encoding="utf-8")
	used = set(re.findall(r'event_name="([A-Z_]+)"', source))
	seeded = {r["name"] for r in db("SELECT name FROM reward_sources")}
	assert used, "expected process_reward_event calls with literal event names"
	assert used <= seeded, f"reward events with no seeded source (they silently pay 0): {sorted(used - seeded)}"


# ---------------------------------------------------------------------------
# API admin operations mirror the web ledger convention
# ---------------------------------------------------------------------------
def test_api_settle_writes_a_negative_ledger_row(anon, world, db):
	maya = world.users["maya.student"]
	before = _wallet(db, maya)
	response = anon.post("/api/v1/rewards/settle", json={"target_user_id": maya, "points": 100}, headers=world.api_keys["admin"])
	assert response.status_code == 200, response.get_json()
	row = dict(db("SELECT * FROM reward_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (maya,))[0])
	assert row["points"] == -100 and row["transaction_type"] == "SETTLEMENT"
	assert row["balance_before"] == before["current_balance"] and row["balance_after"] == before["current_balance"] - 100
	assert row["created_by"] == world.users["admin"]
	after = _wallet(db, maya)
	assert after["current_balance"] == before["current_balance"] - 100
	assert after["total_settled"] == before["total_settled"] + 100
	assert _ledger_sum(db, maya) == after["current_balance"]


def test_api_adjust_stores_signed_points(anon, world, db):
	maya = world.users["maya.student"]
	before = _wallet(db, maya)
	response = anon.post("/api/v1/rewards/adjust", json={"target_user_id": maya, "points": -40, "description": "correction"}, headers=world.api_keys["admin"])
	assert response.status_code == 200, response.get_json()
	row = dict(db("SELECT * FROM reward_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (maya,))[0])
	assert row["points"] == -40 and row["transaction_type"] == "REVERSAL"
	assert row["created_by"] == world.users["admin"]
	after = _wallet(db, maya)
	assert after["current_balance"] == before["current_balance"] - 40
	assert after["total_adjusted"] == before["total_adjusted"] + 40
	assert _ledger_sum(db, maya) == after["current_balance"]


def test_api_reset_writes_a_negative_row_and_grows_total_adjusted(anon, world, db):
	maya = world.users["maya.student"]
	before = _wallet(db, maya)
	response = anon.post("/api/v1/rewards/reset", json={"target_user_id": maya}, headers=world.api_keys["admin"])
	assert response.status_code == 200, response.get_json()
	row = dict(db("SELECT * FROM reward_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (maya,))[0])
	assert row["points"] == -before["current_balance"] and row["balance_after"] == 0
	after = _wallet(db, maya)
	assert after["current_balance"] == 0
	assert after["total_adjusted"] == before["total_adjusted"] + before["current_balance"]
	assert _ledger_sum(db, maya) == 0


@pytest.mark.parametrize("path, payload", [
	("/api/v1/rewards/settle", {"points": "ten"}),
	("/api/v1/rewards/adjust", {"points": "ten"}),
	("/api/v1/rewards/adjust", {"points": 0}),
])
def test_api_reward_operations_reject_bad_points_with_400(anon, world, path, payload):
	payload = {"target_user_id": world.users["maya.student"], **payload}
	response = anon.post(path, json=payload, headers=world.api_keys["admin"])
	assert response.status_code == 400, response.get_data(as_text=True)[:200]


def test_ledger_sum_equals_balance_after_mixed_web_and_api_operations(admin, anon, world, db, db_path):
	maya = world.users["maya.student"]
	_fire(db_path, user_id=maya, event_name="COMMUNITY_POST_RATING", source_reference_id="PRATE-7-7", source_reference_type="post", description="t", input_value=5)
	assert admin.post("/admin/rewards/settle", data={"user_id": maya, "points": "50", "remarks": "web settle"}).status_code == 302
	assert admin.post("/admin/rewards/adjust", data={"user_id": maya, "points": "-20", "remarks": "web debit"}).status_code == 302
	assert anon.post("/api/v1/rewards/adjust", json={"target_user_id": maya, "points": 30}, headers=world.api_keys["admin"]).status_code == 200
	assert anon.post("/api/v1/rewards/settle", json={"target_user_id": maya, "points": 10}, headers=world.api_keys["admin"]).status_code == 200
	_fire(db_path, user_id=maya, event_name="COMMUNITY_POST_RATING", source_reference_id="PRATE-7-7", source_reference_type="post", description="t", input_value=1)
	wallet = _wallet(db, maya)
	assert _ledger_sum(db, maya) == wallet["current_balance"]
	for row in db("SELECT * FROM reward_transactions WHERE user_id = ?", (maya,)):
		assert row["balance_after"] - row["balance_before"] == row["points"], dict(row)


# ---------------------------------------------------------------------------
# web admin routes
# ---------------------------------------------------------------------------
def test_admin_adjust_with_a_non_numeric_user_id_flashes_instead_of_crashing(admin, world):
	response = admin.post("/admin/rewards/adjust", data={"user_id": "abc", "points": "5", "remarks": "x"}, follow_redirects=True)
	assert response.status_code == 200
	assert b"Select a user" in response.data or b"user" in response.data.lower()


def test_admin_settle_with_a_missing_user_id_flashes_instead_of_crashing(admin, world):
	response = admin.post("/admin/rewards/settle", data={"points": "5", "remarks": "x"}, follow_redirects=True)
	assert response.status_code == 200


def test_admin_rewards_page_lists_basic_users(admin, world, db):
	page = admin.get("/admin/rewards")
	assert page.status_code == 200
	assert b"Maya Student" in page.data
