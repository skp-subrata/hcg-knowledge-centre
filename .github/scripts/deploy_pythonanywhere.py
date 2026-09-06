#!/usr/bin/env python3
"""Deploy the current git tree to PythonAnywhere via its REST API. No SSH, no console.

This uploads every git-tracked file through the Files API and then reloads the web app.
That alone is enough to pick up code, template, static-asset and init_scripts/*.sql changes,
because app.py calls init_db() unconditionally at import time (inside create_app(), itself
called at module scope) -- reloading forces a fresh import, which re-applies any new init
script and re-runs the idempotent demo/catalogue seeding. No console step is needed for any
of that.

What this script deliberately does NOT do:
- Install new pip packages. That needs an executed process, and PythonAnywhere's Consoles
  API refuses to run anything until a human has loaded that console's URL in a browser once
  -- something a CI runner can never do. So before uploading anything, it compares the local
  requirements.txt against the one already deployed; if they differ, it stops with
  instructions to install the new dependency by hand first (see the "Updating later" section
  of docs/DEPLOY_PYTHONANYWHERE.md), then push again.
- Delete files. A file removed from git stays on the server until removed by hand. This is
  deliberate: an add/update-only sync can never accidentally delete users.db, uploads/ or any
  other runtime file, because git-ignored paths never appear in the upload set in the first
  place (see tracked_files()).

Required environment variables for a real deploy: PYTHONANYWHERE_USERNAME,
PYTHONANYWHERE_API_TOKEN. Neither is needed for --dry-run, which makes no network calls at
all (including skipping the requirements.txt comparison, since that needs the remote copy).
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_DIR_NAME = "hcg-knowledge-centre"
API_BASE = "https://www.pythonanywhere.com/api/v0/user/{username}"
UPLOAD_PACE_SECONDS = 1.5  # keeps us comfortably under the Files API's 40 requests/minute limit
MAX_RETRIES = 3


def tracked_files():
	"""Every file git tracks in the current tree -- the exact set to sync. Anything git
	ignores (uploads/, users.db, venv/, .secret_key, ...) never appears here, so an
	add/update-only sync structurally cannot touch runtime data."""
	output = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
	return [line for line in output.splitlines() if line.strip()]


def requirements_changed(remote_content, local_content):
	"""Pure comparison: True only when a requirement.txt is already deployed AND differs from
	what we're about to push. Nothing deployed yet (remote_content is None) is not a change --
	there's nothing to compare against, so the very first deploy to a fresh account is not
	blocked by this guard."""
	return remote_content is not None and remote_content != local_content


def backoff_delay(attempt):
	"""Seconds to wait before retry number `attempt` (1-indexed)."""
	return UPLOAD_PACE_SECONDS * attempt


def fetch_remote_requirements(session, base_url, username):
	url = f"{base_url}/files/path/home/{username}/{REPO_DIR_NAME}/requirements.txt"
	response = session.get(url)
	if response.status_code == 404:
		return None
	response.raise_for_status()
	return response.text


def upload(session, base_url, username, path, retries=MAX_RETRIES):
	url = f"{base_url}/files/path/home/{username}/{REPO_DIR_NAME}/{path}"
	content = Path(path).read_bytes()
	last_response = None
	for attempt in range(1, retries + 1):
		response = session.post(url, files={"content": (Path(path).name, content)})
		if response.status_code == 429 or response.status_code >= 500:
			last_response = response
			time.sleep(backoff_delay(attempt))
			continue
		response.raise_for_status()
		return response.status_code
	last_response.raise_for_status()


def reload_webapp(session, base_url, domain):
	response = session.post(f"{base_url}/webapps/{domain}/reload/")
	response.raise_for_status()
	return response.json()


def smoke_test(domain, attempts=5, delay=3):
	url = f"https://{domain}/api/v1/releases/active"
	last_error = None
	for _ in range(attempts):
		try:
			response = requests.get(url, timeout=10)
			if response.status_code == 200:
				return True
		except requests.RequestException as error:
			last_error = error
		time.sleep(delay)
	raise SystemExit(f"Smoke test failed: {url} did not return 200 after {attempts} attempts ({last_error})")


REQUIREMENTS_GUARD_MESSAGE = (
	"requirements.txt differs from what is already deployed on PythonAnywhere. This pipeline "
	"cannot install new dependencies: PythonAnywhere's console API refuses to run anything "
	"until a human has opened it once in a browser, which a CI runner can't do. Install the "
	"new dependency by hand first (see the 'Updating later' section of "
	"docs/DEPLOY_PYTHONANYWHERE.md), then push again."
)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--dry-run", action="store_true", help="Print what would happen; make no network calls.")
	args = parser.parse_args()

	files = tracked_files()
	print(f"{len(files)} tracked files to sync.")

	if args.dry_run:
		for path in files:
			print(f"  would upload: {path}")
		print("Dry run: no network calls made (requirements.txt comparison skipped).")
		return

	username = os.environ["PYTHONANYWHERE_USERNAME"]
	token = os.environ["PYTHONANYWHERE_API_TOKEN"]
	domain = f"{username}.pythonanywhere.com"
	base_url = API_BASE.format(username=username)

	session = requests.Session()
	session.headers["Authorization"] = f"Token {token}"

	remote_requirements = fetch_remote_requirements(session, base_url, username)
	local_requirements = Path("requirements.txt").read_text()
	if requirements_changed(remote_requirements, local_requirements):
		sys.exit(REQUIREMENTS_GUARD_MESSAGE)

	for index, path in enumerate(files, start=1):
		upload(session, base_url, username, path)
		print(f"  [{index}/{len(files)}] uploaded {path}")
		time.sleep(UPLOAD_PACE_SECONDS)

	print("Reloading the web app...")
	reload_webapp(session, base_url, domain)

	print("Smoke testing...")
	smoke_test(domain)
	print(f"Deploy complete: https://{domain}")


if __name__ == "__main__":
	main()
