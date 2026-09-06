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

app_module.app.config.update(TESTING=True, CSRF_ENABLED=False)  # tests/test_csrf.py re-enables it per test

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

	The app always sets ``role='basic user'`` on login; staff must ``POST /switch-role``.
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


@pytest.fixture
def world(db_path):
	"""The seeded database plus a group, posts, an attempt, a certified course, a wallet and API keys."""
	from tests.helpers import build_world

	return build_world(db_path, app_module.UPLOAD_FOLDER)
