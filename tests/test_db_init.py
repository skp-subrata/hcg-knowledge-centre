"""Schema creation, init scripts and seeding behave on fresh and existing databases."""
import json
import sqlite3

import pytest

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


def test_active_release_is_1_7_0_and_earlier_releases_are_retired(db):
	active = db("SELECT version_number, features, improvements, bug_fixes FROM app_releases WHERE is_active = 1")
	assert len(active) == 1 and active[0]["version_number"] == "1.7.0"
	for column in ("features", "improvements", "bug_fixes"):
		assert json.loads(active[0][column]), f"{column} must be non-empty JSON so the release sheet has something to show"
	retired = {r["version_number"] for r in db("SELECT version_number FROM app_releases WHERE is_active = 0")}
	assert {"1.6.1", "1.5.0", "1.4.0", "1.3.2"} <= retired


def test_statements_keeps_a_trailing_statement_without_a_semicolon():
	from db_init import _statements

	statements = [item.strip() for item in _statements("CREATE TABLE a (x);\n-- comment only\nINSERT INTO a VALUES (1)")]
	assert len(statements) == 2
	assert statements[0] == "CREATE TABLE a (x);"
	assert statements[1].endswith("INSERT INTO a VALUES (1)"), "the unterminated tail is still executed"


def test_duplicate_add_column_is_skipped_but_other_errors_are_raised(tmp_path):
	import sqlite3

	from db_init import apply_init_scripts

	scripts = tmp_path / "scripts"; scripts.mkdir()
	(scripts / "001_base.sql").write_text("CREATE TABLE t (id INTEGER);\nALTER TABLE t ADD COLUMN id INTEGER;\nALTER TABLE t ADD COLUMN extra TEXT;\n")
	connection = sqlite3.connect(tmp_path / "x.db")
	assert apply_init_scripts(connection, scripts) == ["001_base.sql"], "the duplicate ADD COLUMN is tolerated"
	assert [row[1] for row in connection.execute("PRAGMA table_info(t)")] == ["id", "extra"]

	(scripts / "002_broken.sql").write_text("INSERT INTO missing_table VALUES (1);\n")
	with pytest.raises(RuntimeError, match="002_broken.sql failed"):
		apply_init_scripts(connection, scripts)
	assert [name for name, _ in __import__("db_init").applied_scripts(connection)] == ["001_base.sql"], "a failing script is not recorded"


def test_cli_main_reports_the_database_and_applied_scripts(db_path, capsys):
	import db_init

	db_init.main()
	out = capsys.readouterr().out
	assert "Database ready" in out and str(db_path) in out
	assert "000_" in out and "006_" in out


def test_demo_seeding_skips_rehashing_once_already_seeded(monkeypatch, tmp_path):
	"""generate_password_hash uses scrypt; re-hashing ~106 rows on every restart is expensive
	CPU that buys nothing once the rows already exist (QA: burns a CPU-metered host's daily quota)."""
	fresh = tmp_path / "fresh.db"
	monkeypatch.setattr(app_module, "DATABASE", fresh)
	app_module.init_db()  # first boot: seeds everything

	calls = []
	real_hash = app_module.generate_password_hash
	monkeypatch.setattr(app_module, "generate_password_hash", lambda *a, **k: (calls.append(a), real_hash(*a, **k))[1])

	connection = sqlite3.connect(fresh)
	connection.row_factory = sqlite3.Row
	try:
		app_module.seed_demo_data(connection)  # second boot: same database, nothing new to hash
		assert calls == [], f"re-hashed {len(calls)} passwords on a restart that seeded nothing new"

		# The per-restart course/assessment backfill must still run, so a course created after the
		# first boot still gets its sample assessment.
		admin_id = connection.execute("SELECT id FROM users WHERE username = 'subratakumar.pradhan'").fetchone()["id"]
		new_course_id = connection.execute(
			"INSERT INTO courses (name, description, category, content_type, content_url, created_by) VALUES ('A Brand New Course', 'd', 'General', 'URL', 'https://example.com', ?)",
			(admin_id,),
		).lastrowid
		app_module.seed_demo_data(connection)
		assessment = connection.execute("SELECT id FROM assessments WHERE course_id = ?", (new_course_id,)).fetchone()
		assert assessment is not None, "seed_course_questions must still back-fill new courses on every restart"
	finally:
		connection.close()


def test_extended_catalog_seeds_courses_posts_and_named_users(db):
	assert db("SELECT COUNT(*) AS n FROM courses")[0]["n"] >= 7
	named = db("SELECT COUNT(*) AS n FROM users WHERE username = 'priya.nair'")[0]["n"]
	assert named == 1
	statuses = {r["status"] for r in db("SELECT DISTINCT status FROM posts")}
	assert {"PUBLISHED", "PENDING_APPROVAL", "REJECTED"} <= statuses
	assert db("SELECT COUNT(*) AS n FROM post_ratings")[0]["n"] > 0
	assert db("SELECT COUNT(*) AS n FROM post_comments")[0]["n"] > 0
	rejected = db("SELECT id FROM posts WHERE status = 'REJECTED' LIMIT 1")[0]["id"]
	assert db("SELECT COUNT(*) AS n FROM post_approval_history WHERE post_id = ? AND action = 'REJECT'", (rejected,))[0]["n"] == 1


def test_extended_catalog_is_idempotent_across_restarts(db_path, db):
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	try:
		before = {t: db(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in ("courses", "posts", "post_ratings", "post_comments", "course_assignments", "users")}
		with connection:
			app_module.seed_demo_data(connection)
		after = {t: db(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in before}
		assert before == after
	finally:
		connection.close()
