# HCG Knowledge Centre

A role-secured Learning Management System (LMS) built with Python, Flask and SQLite. It offers course management, interactive assessments with certificates and badges, a gamified rewards wallet, a community feed with an approval workflow, groups, notifications, and a REST API with an interactive playground.

## Quick start (macOS / Linux)

```bash
git clone https://github.com/skp-subrata/hcg-knowledge-centre.git
cd hcg-knowledge-centre
./run.sh
```

`run.sh` creates a `.venv`, installs `requirements.txt` (only when it changes), initialises the SQLite database (tables, master data and demo data) and starts the app. It prints the URL, normally `http://127.0.0.1:5000`. If port 5000 is busy (macOS AirPlay Receiver uses it) it picks the first free port in 5050-5059 and says so.

| Option | Effect |
|---|---|
| `./run.sh --setup-only` | Create the venv, install dependencies and initialise the database, then exit |
| `./run.sh --port 8000` | Bind to a specific port (same as `LMS_PORT=8000 ./run.sh`) |
| `./run.sh --host 0.0.0.0` | Listen on all interfaces |
| `./run.sh --no-debug` | Disable the Flask debugger and auto-reload |
| `./run.sh --help` | Show all options and environment variables |

## Manual setup (any OS, including Windows)

```bash
python -m venv .venv
# macOS/Linux:            source .venv/bin/activate
# Windows (PowerShell):   .venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app app init-db        # optional: the app also does this on start-up
python app.py
```

On Windows, set variables with `set LMS_PORT=5050` (cmd) or `$env:LMS_PORT=5050` (PowerShell) before `python app.py`. Python 3.8 or newer is required.

## Configuration

All settings are environment variables; every one is optional.

| Variable | Default | Purpose |
|---|---|---|
| `LMS_HOST` | `127.0.0.1` | Bind address |
| `LMS_PORT` | `5000` | Port (`run.sh` falls back to 5050-5059 when 5000 is busy) |
| `LMS_DEBUG` | `1` on loopback hosts, else `0` | `1` enables the Flask debugger and auto-reload |
| `LMS_DATABASE` | `./users.db` | SQLite database file |
| `LMS_UPLOAD_FOLDER` | `./uploads` | Where uploaded course files, attachments and profile pictures are stored |
| `LMS_SECRET_KEY` | generated | Flask session secret. When unset, a random key is generated once and stored in `.secret_key` (git-ignored) |
| `LMS_SECRET_KEY_FILE` | `./.secret_key` | Where the generated key is kept |
| `LMS_CSRF` | `1` | `1` requires a CSRF token on every session-authenticated POST (forms and fetches). API-key requests are exempt. Set `0` only for local debugging. |
| `LMS_SEED_DEMO` | `1` | `1` seeds demo accounts, 100 sample users and two demo courses on start-up. Set `0` for a deployment |

## Database initialisation

Tables are created automatically the first time the app starts, and every start is safe to repeat:

1. `init_db()` in `app.py` creates the core tables and the bootstrap administrator.
2. The SQL scripts in `init_scripts/` are applied in filename order, **once per database**. Applied scripts are recorded in the `schema_migrations` table. This is how the master tables (departments, locations, positions, interests), the extra user columns, starter master data and release notes get there.
3. If `LMS_SEED_DEMO=1`, demo data is seeded with `INSERT OR IGNORE`, so existing rows are never overwritten.

To run the initialisation on its own:

```bash
flask --app app init-db      # or: python db_init.py
```

To start over locally, stop the app and delete `users.db`.

### Adding a schema change

Create `init_scripts/NNN_short_description.sql` with the next number. Use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` and `INSERT OR IGNORE`. `ALTER TABLE ... ADD COLUMN` is also safe: `db_init.py` skips a column that already exists. The script runs the next time the app starts or `flask --app app init-db` is run.

## Demo accounts

Seeded only when `LMS_SEED_DEMO=1`. For local use only.

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `admin` |
| Moderator | `mod` | `mod` |
| Student | `student` | `student` |
| Administrator (bootstrap) | `subratakumar.pradhan` | `admin123` |
| Student with assigned courses | `maya.student` | `learn123` |
| Sample users | `sampleuser001` … `sampleuser100` | `learn123` |

## Roles and switching

Every login starts in the **student view**, whatever the account's role. Administrators and moderators open the avatar menu and choose **Switch role** (or visit `/switch-role`) to enter the staff workspace. Administrators can also **View as** another user to see the app the way that user does, and **Exit view** to return.

- **Admin dashboard** (`/admin`): manage courses, question banks and assessments, assign courses to users or groups, manage users, rewards and API keys.
- **Masters** (`/admin/masters`): departments and locations.
- **Reports** (`/admin/reports`): KPIs plus CSV downloads.
- **API playground** (`/api/v1/docs`, administrators): generate an API key in the admin dashboard, enter it as `X-API-Key` / `X-API-Secret`, and run live requests.

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests use a temporary copy of a freshly seeded database and never touch `users.db`, `uploads/` or the network.

## Project layout

| Path | Purpose |
|---|---|
| `app.py` | The Flask application: routes, schema (`init_db`), demo seeding, reward engine, API v1 |
| `db_init.py` | Applies `init_scripts/*.sql` once each and records them in `schema_migrations` |
| `init_scripts/` | Numbered SQL scripts: master tables, interests, user columns, seed data, release notes |
| `storage.py` | Upload helper with the allowed file types for course content |
| `run.sh` | One-command setup and start (macOS/Linux) |
| `templates/` | Jinja2 templates (Tailwind CSS via CDN) |
| `tests/` | pytest suite |
| `docs/` | Database ER diagram and cloud hosting notes |

## Documentation

- `docs/database_er_diagram.md` — SQLite schema and ER diagram.
- `docs/cloud_hosting_architecture.md` — production deployment and security notes.

## Tech stack

Python 3, Flask, Werkzeug, SQLite; HTML5, Tailwind CSS (CDN), Jinja2, vanilla JavaScript; openpyxl for Excel question imports.
