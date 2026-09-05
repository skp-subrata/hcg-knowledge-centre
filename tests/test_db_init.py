"""Schema creation, init scripts and seeding behave on fresh and existing databases."""
import sqlite3

import app as app_module
from db_init import INIT_SCRIPTS_DIR, apply_init_scripts

EXPECTED_SCRIPTS = sorted(path.name for path in INIT_SCRIPTS_DIR.glob("*.sql"))


def test_every_init_script_is_recorded(db):
	names = [row["name"] for row in db("SELECT name FROM schema_migrations ORDER BY name")]
	assert names == EXPECTED_SCRIPTS
	assert len(names) >= 5


def test_master_tables_and_columns_exist(db):
	tables = {row["name"] for row in db("SELECT name FROM sqlite_master WHERE type = 'table'")}
	assert {
		"departments", "locations", "positions", "interest_master", "user_interest",
		"schema_migrations", "app_releases", "group_moderators",
	} <= tables
	user_columns = {row["name"] for row in db("PRAGMA table_info(users)")}
	assert {
		"department_id", "position_id", "location_id", "about_me",
		"email", "phone_number", "profile_picture", "employee_id", "is_active",
	} <= user_columns
	course_columns = {row["name"] for row in db("PRAGMA table_info(courses)")}
	assert {"tags", "duration_minutes", "difficulty", "thumbnail_color"} <= course_columns


def test_starter_master_data_is_present(db):
	for table in ("departments", "locations", "positions", "interest_master"):
		assert db(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] >= 1, table


def test_demo_accounts_are_seeded(db):
	rows = db("SELECT username, role FROM users WHERE username IN ('admin', 'mod', 'student') ORDER BY username")
	assert [(r["username"], r["role"]) for r in rows] == [
		("admin", "admin"), ("mod", "moderator"), ("student", "basic user"),
	]


def test_init_db_is_idempotent(db):
	def counts():
		tables = [
			row["name"]
			for row in db("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
		]
		return {table: db(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] for table in tables}

	before = counts()
	app_module.init_db()
	app_module.init_db()
	assert counts() == before


def test_second_apply_applies_nothing(db_path):
	connection = sqlite3.connect(db_path)
	try:
		assert apply_init_scripts(connection) == []
	finally:
		connection.close()


def test_flask_init_db_command(db_path):
	result = app_module.app.test_cli_runner().invoke(args=["init-db"])
	assert result.exit_code == 0, result.output
	assert "Database ready" in result.output
	for name in EXPECTED_SCRIPTS:
		assert name in result.output


def test_demo_seeding_can_be_disabled(tmp_path, monkeypatch):
	fresh = tmp_path / "fresh.db"
	monkeypatch.setattr(app_module, "DATABASE", fresh)
	monkeypatch.setenv("LMS_SEED_DEMO", "0")
	app_module.init_db()
	connection = sqlite3.connect(fresh)
	try:
		users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
		departments = connection.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
		columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
	finally:
		connection.close()
	assert users == 1  # only the bootstrap administrator
	assert departments >= 1
	assert {"email", "phone_number", "profile_picture", "department_id"} <= columns


def test_exactly_one_active_release_is_seeded(db):
	active = db("SELECT version_number FROM app_releases WHERE is_active = 1")
	assert len(active) == 1
	assert db("SELECT COUNT(*) AS n FROM app_releases")[0]["n"] >= 2
