# Deploying to PythonAnywhere (free tier)

PythonAnywhere's free "Beginner" account is the option to use for a true, no-cost demo: no
credit card, the web app runs continuously (it does not sleep between visits, unlike Render's
or Koyeb's free tiers), and the 512 MB disk is enough for this app once the unused
`firebase-functions` dependency is out of `requirements.txt` (it never was imported and alone
was ~128 MB — already removed on `dev-akash`).

Trade-offs worth knowing before you pick it:

| limit | what it means here |
|---|---|
| **100 CPU-seconds/day** | Ordinary browsing is light. The one CPU-heavy operation is the first-ever database seed (scrypt-hashing ~106 demo/sample passwords, a few seconds); it only happens once — the app now skips re-hashing on every later restart. If you do exhaust the daily quota, the site serves a "CPU quota" page until PythonAnywhere's midnight UTC reset |
| **512 MB disk** | Covers the virtualenv, the SQLite file and uploaded files. Do not reinstall `firebase-functions` |
| **Outbound web access is allowlisted** | `pypi.org` and `github.com` are both on the free-tier allowlist (needed for `pip install` and `git clone`), so setup works. Course-URL content-type detection and the `/proxy/embed` viewer only reach sites also on that [allowlist](https://www.pythonanywhere.com/whitelist/) — an arbitrary course link may not embed or auto-detect its type; the course still saves and opens in a new tab |
| **3-month renewal** | The web app keeps running 24/7 without any action; every 3 months PythonAnywhere emails you and you log in and click "Run until 3 months from today" once. If you skip it, the app is disabled, not deleted — one click brings it back |

## What I need from you

- A PythonAnywhere account — sign up free at pythonanywhere.com/registration/register/beginner, no card. Share the **username** you chose; nothing else. I never need your password — every step below is something you do in their dashboard/consoles yourself.
- The password you want for the two seeded admin accounts (`admin` and `subratakumar.pradhan`), used to set `LMS_ADMIN_PASSWORD` in step 4.

## Steps

**1. Create the account.** pythonanywhere.com → **Start running Python online in less than a minute!** → Beginner (free) plan.

**2. Open a Bash console** from the Dashboard → **Consoles** → **Bash**.

**3. Clone the repo and install dependencies:**

```bash
git clone -b dev-akash https://github.com/skp-subrata/hcg-knowledge-centre.git
cd hcg-knowledge-centre
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If `python3.11` is not offered, run `python3 --version` first — anything ≥3.10 is fine (the venv
tool name changes accordingly, e.g. `python3.10 -m venv venv`). Installation of `pip` packages
only succeeds because `pypi.org` is allowlisted; nothing above needs any other site.

**4. Initialise the database once, from the same console:**

```bash
LMS_ADMIN_PASSWORD='the password you chose' flask --app app init-db
```

This creates the tables, applies `init_scripts/*.sql`, and seeds the demo accounts and sample
data (the one CPU-heavy step; a few seconds). Everything from here on reuses this same
`users.db` file, so it never repeats.

**5. Create the web app.** Dashboard → **Web** → **Add a new web app** → **Manual configuration**
(not "Flask" — that scaffolds a new project; we already have one) → **Python 3.11**.

**6. Point it at the virtualenv.** On the same Web tab, under **Virtualenv**, enter:

```
/home/<your-username>/hcg-knowledge-centre/venv
```

**7. Edit the WSGI configuration file.** Still on the Web tab, click the path under **Code** →
**WSGI configuration file** (a path like
`/var/www/<your-username>_pythonanywhere_com_wsgi.py`) to open it in their editor. Delete
everything in it and paste this, replacing `<your-username>` and the password in both places:

```python
import sys
import os

path = "/home/<your-username>/hcg-knowledge-centre"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["LMS_DATABASE"] = f"{path}/users.db"
os.environ["LMS_UPLOAD_FOLDER"] = f"{path}/uploads"
os.environ["LMS_SECRET_KEY_FILE"] = f"{path}/.secret_key"
os.environ["LMS_DEBUG"] = "0"
os.environ["LMS_SECURE_COOKIES"] = "1"    # PythonAnywhere always serves https://<user>.pythonanywhere.com
os.environ["LMS_CSRF"] = "1"
os.environ["LMS_SEED_DEMO"] = "1"         # harmless to leave on: seeding is now skipped once already done
os.environ["LMS_ADMIN_PASSWORD"] = "the password you chose"

from app import app as application
```

Save the file.

**8. (Optional, faster static files.)** On the Web tab, under **Static files**, add a mapping:
URL `/static/` → Directory `/home/<your-username>/hcg-knowledge-centre/static/`.

**9. Reload.** Click the big green **Reload** button at the top of the Web tab. Open
`https://<your-username>.pythonanywhere.com`, sign in as `admin` with the password you chose,
and change or deactivate the `mod`/`student` demo accounts before sharing the link.

## Updating later

```bash
cd ~/hcg-knowledge-centre
git pull
source venv/bin/activate
pip install -r requirements.txt
flask --app app init-db     # safe to re-run: only applies new init_scripts, does not reseed
```
Then click **Reload** on the Web tab again.

## Continuous deployment

Pushing to the `staging` branch redeploys automatically via `.github/workflows/deploy-staging.yml`
— no console, no manual steps, for ordinary code/template/static-asset changes.

**How it works:** the workflow runs `.github/scripts/deploy_pythonanywhere.py`, which uploads
every git-tracked file through the Files API (never touches anything git ignores — `venv/`,
`users.db`, `uploads/`, `.secret_key` — since those never appear in `git ls-files`) and then
reloads the web app. Reloading forces `app.py` to re-import, which re-runs `init_db()` and
therefore applies any new `init_scripts/*.sql` and the idempotent demo/catalogue seeding — the
same effect as the "Updating later" steps above, just automatic. A short smoke test
(`GET /api/v1/releases/active`) confirms the site is actually up before the job reports success.

**One-time setup, needed once:**

1. Get **Admin** or **Maintain** access on the GitHub repo (Actions secrets need it; regular
   push access is not enough). Ask the repo owner if you don't have it.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `PYTHONANYWHERE_USERNAME` — the account's username
   - `PYTHONANYWHERE_API_TOKEN` — its API token (Account → API Token). Prefer a freshly
     regenerated one over reusing a token that has been shared anywhere else.

**The one thing it can't automate:** installing a *new* pip package needs an executed process,
and PythonAnywhere's Consoles API refuses to run anything until a human has loaded that
console's URL in a browser once — a CI runner can never do that. So the script compares the
local `requirements.txt` against the one already deployed before uploading anything; if they
differ, the job fails with a message pointing back to the manual "Updating later" steps above.
Do that once by hand, then push again — every deploy after that (until the next new
dependency) goes through the automated path.

`python .github/scripts/deploy_pythonanywhere.py --dry-run` runs locally with no network calls
at all, useful to sanity-check the file list before trusting a real push.

## Keeping it running

Every 3 months PythonAnywhere emails you; log in, open the **Web** tab, click **"Run until 3
months from today"**. That is the only recurring task — the app itself runs continuously in
between, it does not sleep on idle the way Render's or Koyeb's free tiers do.

## When you outgrow it

`docs/DEPLOY_RENDER.md` covers a paid Render instance with a persistent disk (no CPU-second
metering, arbitrary outbound URLs, no renewal clicks) using the same `render.yaml`.
