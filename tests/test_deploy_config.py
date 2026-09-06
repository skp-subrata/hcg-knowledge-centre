"""Hosting switches used by render.yaml (reverse proxy, secure cookies, seeded admin password) and the blueprint itself."""
import re
import sqlite3
from pathlib import Path

from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import app as app_module

ROOT = Path(__file__).resolve().parents[1]


def test_proxy_fix_and_secure_cookies_are_opt_in(monkeypatch, db_path):
	plain = app_module.create_app()
	assert not isinstance(plain.wsgi_app, ProxyFix) and not plain.config.get("SESSION_COOKIE_SECURE")
	monkeypatch.setenv("LMS_PROXY_FIX", "1")
	monkeypatch.setenv("LMS_SECURE_COOKIES", "1")
	hosted = app_module.create_app()
	assert isinstance(hosted.wsgi_app, ProxyFix)
	assert hosted.config["SESSION_COOKIE_SECURE"] is True
	assert hosted.config["SESSION_COOKIE_HTTPONLY"] is True and hosted.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_forwarded_proto_is_trusted_when_enabled(monkeypatch, db_path):
	monkeypatch.setenv("LMS_PROXY_FIX", "1")
	hosted = app_module.create_app()
	hosted.config.update(TESTING=True, CSRF_ENABLED=False)
	client = hosted.test_client()
	# Anonymous POST to a protected page redirects home; behind the proxy the Location must be https.
	response = client.post("/admin", data={"action": "add_course"}, headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "lms.example.com"})
	assert response.status_code in (302, 303)
	assert response.headers["Location"].startswith(("https://lms.example.com/", "/")), response.headers["Location"]


def test_seeded_admin_takes_the_password_from_the_environment(monkeypatch, tmp_path):
	# A fresh database, not the shared seeded one: seed_demo_data() skips its (expensive, scrypt-hashed)
	# insert loops once the demo dataset already exists, so this has to run against an empty database.
	monkeypatch.setenv("LMS_ADMIN_PASSWORD", "s3cret-from-render")
	fresh = tmp_path / "fresh.db"
	monkeypatch.setattr(app_module, "DATABASE", fresh)
	app_module.init_db()
	connection = sqlite3.connect(fresh)
	connection.row_factory = sqlite3.Row
	rows = {r["username"]: r["password_hash"] for r in connection.execute("SELECT username, password_hash FROM users WHERE username IN ('admin', 'mod', 'subratakumar.pradhan')")}
	connection.close()
	assert check_password_hash(rows["admin"], "s3cret-from-render") and not check_password_hash(rows["admin"], "admin")
	assert check_password_hash(rows["subratakumar.pradhan"], "s3cret-from-render"), "the bootstrap admin honours the same variable"
	assert check_password_hash(rows["mod"], "mod"), "other demo accounts are unchanged"


def test_render_blueprint_matches_the_app_configuration():
	text = (ROOT / "render.yaml").read_text(encoding="utf-8")
	assert "startCommand: gunicorn" in text and "app:app" in text
	assert "--workers 1" in text, "SQLite: keep a single writer process"
	mount = re.search(r"mountPath: (\S+)", text).group(1)
	for key in ("LMS_DATABASE", "LMS_UPLOAD_FOLDER"):
		value = re.search(key + r"\n\s+value: (\S+)", text).group(1)
		assert value.startswith(mount + "/"), f"{key} must live on the persistent disk"
	app_source = (ROOT / "app.py").read_text(encoding="utf-8") + (ROOT / "security.py").read_text(encoding="utf-8")
	for key in re.findall(r"- key: (LMS_[A-Z_]+)", text):
		assert key in app_source, f"render.yaml sets {key} but nothing reads it"
	assert "gunicorn" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_windows_bootstrap_mirrors_run_sh():
	ps1 = (ROOT / "run.ps1").read_text(encoding="utf-8")
	sh = (ROOT / "run.sh").read_text(encoding="utf-8")
	for needle in ("-m venv", ".venv", "requirements.txt", "flask --app app init-db", "app.py"):
		assert needle in ps1 and needle in sh, needle
	assert "SetupOnly" in ps1 and "--setup-only" in sh
