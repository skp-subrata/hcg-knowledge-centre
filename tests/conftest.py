"""Shared pytest fixtures.

The application builds itself at import time (``app = create_app()`` runs
``init_db()`` and seeds demo data) and reads ``LMS_DATABASE`` when imported.
So this module, in order:

1. points the app at a throw-away *seed* database and makes password hashing
   cheap BEFORE importing it (seeding ~106 users with scrypt takes 10-30 s);
2. imports the app once per test session, which seeds that database;
3. gives every test its own copy of the seeded database via ``db_path``.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="hkc-tests-"))
SEED_DB = _SESSION_DIR / "seed.db"
os.environ["LMS_DATABASE"] = str(SEED_DB)
os.environ["LMS_UPLOAD_FOLDER"] = str(_SESSION_DIR / "uploads")
os.environ["LMS_SECRET_KEY"] = "test-secret"
os.environ["LMS_SEED_DEMO"] = "1"
os.environ["LMS_DEBUG"] = "0"

import werkzeug.security as _ws  # noqa: E402

_real_generate_password_hash = _ws.generate_password_hash


def _fast_generate_password_hash(password, method="pbkdf2:sha256:1000", salt_length=8):
	return _real_generate_password_hash(password, method=method, salt_length=salt_length)


_ws.generate_password_hash = _fast_generate_password_hash

import app as app_module  # noqa: E402  - builds the app and seeds SEED_DB

app_module.app.config.update(TESTING=True)

DEMO_PASSWORDS = {
	"admin": "admin",
	"mod": "mod",
	"student": "student",
	"subratakumar.pradhan": "admin123",
	"maya.student": "learn123",
	"rohan.student": "learn123",
	"aarav.moderator": "learn123",
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
	"""A private copy of the seeded database; the app is pointed at it for this test."""
	path = tmp_path / "test.db"
	shutil.copyfile(SEED_DB, path)
	uploads = tmp_path / "uploads"
	uploads.mkdir()
	monkeypatch.setattr(app_module, "DATABASE", path)
	monkeypatch.setattr(app_module, "UPLOAD_FOLDER", uploads)
	return path


@pytest.fixture
def db(db_path):
	"""``db(sql, params)`` runs one statement against the test database and returns rows."""

	def query(sql, params=()):
		connection = sqlite3.connect(db_path)
		connection.row_factory = sqlite3.Row
		try:
			with connection:
				return connection.execute(sql, params).fetchall()
		finally:
			connection.close()

	return query


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
	"""Tests never reach the network: block urlopen and stub the content-type probe."""
	import urllib.request

	def _blocked(*args, **kwargs):
		raise RuntimeError("network access is disabled in tests")

	monkeypatch.setattr(urllib.request, "urlopen", _blocked)
	monkeypatch.setattr(app_module, "detect_content_type", lambda value: "URL")


@pytest.fixture
def make_client(db_path):
	"""``make_client(username, active_role)`` returns a test client with a ready session.

	The session is written directly (no login form). ``active_role`` is the effective
	role (what the app calls ``role``); it defaults to 'basic user' exactly like a
	real login does, so pass 'admin' / 'moderator' for the staff workspace.
	"""

	def _make(username=None, active_role=None):
		client = app_module.app.test_client()
		if username:
			connection = sqlite3.connect(db_path)
			connection.row_factory = sqlite3.Row
			user = connection.execute(
				"SELECT id, full_name, role FROM users WHERE username = ?", (username,)
			).fetchone()
			connection.close()
			assert user is not None, f"no seeded user {username!r}"
			with client.session_transaction() as sess:
				sess.update(
					user_id=user["id"],
					user=user["full_name"],
					actual_role=user["role"],
					role=active_role or "basic user",
					profile_picture="",
				)
		return client

	return _make


@pytest.fixture
def anon(make_client):
	return make_client()


@pytest.fixture
def student(make_client):
	return make_client("student")


@pytest.fixture
def moderator(make_client):
	return make_client("mod", "moderator")


@pytest.fixture
def admin(make_client):
	return make_client("admin", "admin")


@pytest.fixture
def login():
	"""Real form login: ``login(client, username, password=None)``.

	The app always sets ``role='basic user'`` on login; staff must ``GET /switch-role``.
	"""

	def _login(client, username, password=None):
		password = DEMO_PASSWORDS[username] if password is None else password
		return client.post("/", data={"username": username, "password": password})

	return _login


@pytest.fixture
def api_headers(db_path):
	"""``api_headers(username)`` inserts an active API credential and returns the headers."""

	def _for(username):
		connection = sqlite3.connect(db_path)
		try:
			with connection:
				user_id = connection.execute(
					"SELECT id FROM users WHERE username = ?", (username,)
				).fetchone()[0]
				connection.execute(
					"UPDATE api_credentials SET status = 'inactive' WHERE user_id = ?", (user_id,)
				)
				connection.execute(
					"INSERT INTO api_credentials (user_id, api_key, api_secret, status) VALUES (?, ?, ?, 'active')",
					(user_id, f"ak_test_{username}", f"as_test_{username}"),
				)
		finally:
			connection.close()
		return {"X-API-Key": f"ak_test_{username}", "X-API-Secret": f"as_test_{username}"}

	return _for


# ---------------------------------------------------------------------------
# Route x role matrix output (see tests/test_route_matrix.py)
# ---------------------------------------------------------------------------
def pytest_addoption(parser):
	parser.addoption(
		"--matrix-out",
		action="store",
		default=None,
		help="write the route x role smoke matrix to this markdown file after the run",
	)


def pytest_sessionfinish(session, exitstatus):
	out = session.config.getoption("--matrix-out")
	if not out:
		return
	from tests.helpers import MATRIX_RESULTS

	if not MATRIX_RESULTS:
		return
	personas = ["anon", "student", "mod", "admin", "imp_admin", "api_student", "api_mod", "api_admin"]
	lines = [
		"# Route x role smoke matrix",
		"",
		"Generated by `pytest tests/test_route_matrix.py --matrix-out docs/ROUTE_ROLE_MATRIX.md`. Do not edit by hand.",
		"",
		"Cell = HTTP status observed. `-` = persona not applicable to that surface.",
		"Web personas hold a session (staff after /switch-role; `imp_admin` is an admin impersonating a student).",
		"API personas send X-API-Key / X-API-Secret headers only.",
		"",
		"| Method | Rule | " + " | ".join(personas) + " |",
		"|---|---|" + "---|" * len(personas),
	]
	for (rule, method), results in sorted(MATRIX_RESULTS.items(), key=lambda item: (item[0][0], item[0][1])):
		cells = [str(results.get(p, "-")) for p in personas]
		lines.append(f"| {method} | `{rule}` | " + " | ".join(cells) + " |")
	Path(out).parent.mkdir(parents=True, exist_ok=True)
	Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def world(db_path):
	"""The seeded database plus a group, posts, an attempt, a certified course, a wallet and API keys."""
	from tests.helpers import build_world

	return build_world(db_path, app_module.UPLOAD_FOLDER)
