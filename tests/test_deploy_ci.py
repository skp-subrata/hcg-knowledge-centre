"""Unit tests for .github/scripts/deploy_pythonanywhere.py's pure logic -- no network calls.

Loaded by file path (importlib) since the script lives under .github/, not a normal package.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "deploy_pythonanywhere.py"

spec = importlib.util.spec_from_file_location("deploy_pythonanywhere", SCRIPT_PATH)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_script_exists_and_is_syntactically_valid():
	assert SCRIPT_PATH.is_file()


# ---------------------------------------------------------------------------
# requirements_changed(): the guard that stops a deploy needing a new pip package
# ---------------------------------------------------------------------------
def test_requirements_unchanged_is_not_a_change():
	assert deploy.requirements_changed("Flask>=3.0\n", "Flask>=3.0\n") is False


def test_requirements_differing_is_a_change():
	assert deploy.requirements_changed("Flask>=3.0\n", "Flask>=3.0\nrequests>=2\n") is True


def test_nothing_deployed_yet_is_not_a_change():
	"""The very first deploy to a fresh PythonAnywhere account must not be blocked -- there is
	nothing on the server yet to differ from."""
	assert deploy.requirements_changed(None, "Flask>=3.0\n") is False


# ---------------------------------------------------------------------------
# backoff_delay(): retry pacing math
# ---------------------------------------------------------------------------
def test_backoff_delay_scales_with_attempt_number():
	assert deploy.backoff_delay(1) == deploy.UPLOAD_PACE_SECONDS
	assert deploy.backoff_delay(2) == deploy.UPLOAD_PACE_SECONDS * 2
	assert deploy.backoff_delay(3) > deploy.backoff_delay(2) > deploy.backoff_delay(1)


# ---------------------------------------------------------------------------
# tracked_files(): the exact sync set, respecting .gitignore, never runtime data
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
	repo = tmp_path / "repo"
	repo.mkdir()
	subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
	subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
	subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
	(repo / "app.py").write_text("print('hi')\n")
	(repo / "requirements.txt").write_text("Flask>=3.0\n")
	(repo / "templates").mkdir()
	(repo / "templates" / "index.html").write_text("<h1>hi</h1>\n")
	(repo / ".gitignore").write_text("uploads/\n*.db\n.secret_key\nvenv/\n")
	(repo / "uploads").mkdir()
	(repo / "uploads" / "photo.jpg").write_text("binary-ish")
	(repo / "users.db").write_text("sqlite-ish")
	(repo / ".secret_key").write_text("shh")
	(repo / "venv").mkdir()
	(repo / "venv" / "pyvenv.cfg").write_text("home = /usr\n")
	subprocess.run(["git", "add", "app.py", "requirements.txt", "templates", ".gitignore"], cwd=repo, check=True)
	subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
	monkeypatch.chdir(repo)
	return repo


def test_tracked_files_lists_only_what_git_tracks(fake_repo):
	files = set(deploy.tracked_files())
	assert files == {"app.py", "requirements.txt", "templates/index.html", ".gitignore"}


def test_tracked_files_never_includes_gitignored_runtime_data(fake_repo):
	files = set(deploy.tracked_files())
	assert "uploads/photo.jpg" not in files
	assert "users.db" not in files
	assert ".secret_key" not in files
	assert "venv/pyvenv.cfg" not in files
