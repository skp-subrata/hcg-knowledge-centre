# Test strategy

How `dev-akash` is verified, how to run it, and how to extend it.

## Run

```bash
.venv/bin/python -m pip install -r requirements-dev.txt        # pytest, pytest-cov (playwright optional, see below)
.venv/bin/python -m pytest                                      # whole suite, ~5 s
.venv/bin/python -m pytest --cov=app --cov=storage --cov=db_init --cov=security --cov=csrf --cov-report=term-missing
.venv/bin/python -m pytest tests/test_route_matrix.py --matrix-out docs/ROUTE_ROLE_MATRIX.md   # regenerate the matrix
.venv/bin/python -m playwright install chromium && .venv/bin/python qa/browser_qa.py            # browser pass (~90 s)
```

`pytest.ini` sets `testpaths = tests`. Run a single file or `-k pattern` as usual.

## Architecture

The app is a single Flask factory whose `create_app()` runs at import, reading `LMS_DATABASE` at that moment. `tests/conftest.py` therefore:

1. sets `LMS_DATABASE`, `LMS_UPLOAD_FOLDER`, `LMS_SECRET_KEY`, `LMS_SEED_DEMO=1`, `LMS_DEBUG=0` **before** `import app`;
2. patches `werkzeug.security.generate_password_hash` to a cheap pbkdf2 so seeding ~106 demo users takes milliseconds instead of ~20 s of scrypt;
3. imports the app once, which seeds a session-wide `seed.db`;
4. copies `seed.db` into a fresh `tmp_path` for every test and points `app_module.DATABASE` at it, so tests never share state;
5. sets `TESTING=True` (500s surface as exceptions) and `CSRF_ENABLED=False` (form posts need no token; `tests/test_csrf.py` re-enables it per test);
6. blocks outbound network (`urllib.request.urlopen`) and stubs `detect_content_type`, which would otherwise probe every course URL.

`tests/helpers.py` builds the **world** the demo seed lacks: a group with a moderator and member, a published, a pending and a draft post, a passing attempt, a certification, API credentials and a planted upload. Every id a test needs is a field on `World`.

## Personas

| fixture | who | how |
|---|---|---|
| `anon` | no session | plain client |
| `student` / `maya` | learners (`student` has a certification path; `maya.student` has assignments, an attempt and a notification) | session written directly |
| `moderator` | `mod` elevated to moderator | session with `role=moderator` |
| `admin` | `admin` elevated | session with `role=admin` |
| `imp_admin` (matrix only) | admin impersonating `maya.student` | `/admin/view-as/<id>` |
| `api_student` / `api_mod` / `api_admin` | API-key callers | `api_headers(username)` inserts an `api_credentials` row |

Login always yields `role='basic user'`; staff reach their workspace by **POST `/switch-role`**. Tests that need the real flow use the `login` fixture (form POST) rather than writing the session.

## Layers

| layer | file(s) | what it proves |
|---|---|---|
| Startup & schema | `test_db_init.py`, `test_smoke.py` | init scripts apply once, are recorded in `schema_migrations`, tolerate re-runs and existing columns; demo accounts log in; role switch works |
| Route × role matrix | `test_route_matrix.py` (+ `POLICY`) | every URL rule × eight personas: no 5xx, no `Traceback`, denial classified (302 to `/`, 401/403), anonymous 200 only on the public allow-list, unknown ids and path traversal handled. New routes **must** get a `POLICY` row or the test fails |
| Flows | `test_assessments.py`, `test_rewards.py`, `test_community.py`, `test_groups.py`, `test_admin.py`, `test_api_v1.py`, `test_validation.py` | learner journey (assign → assess → retake rules → certify → feedback → certificate), ledger invariant `SUM(points) == balance` on both surfaces, approvals state machine, rating/comment rules, admin CRUD, API contracts, bad-input 400s |
| Security | `test_security.py`, `test_security_helpers.py`, `test_csrf.py` | privilege boundaries (moderator vs admin, impersonation vs role switch), inactive users, SSRF guard, attachment allowlist, upload serving, secret key persistence, HTML sanitiser, CSRF token lifecycle and exemptions |
| Rendering | `test_render.py` | every template compiles; every page renders for the right persona on the shared layout with exactly one `<h1>` and one `<main>`, no `focus:outline-none`, no leaked Jinja, toast region present; error pages branded for browsers and JSON for API callers |
| Browser | `qa/browser_qa.py` → `docs/qa/browser_report.md` | real Chromium: 30 pages × (1280 light, 1280 dark, 375), console/network errors, a11y checks (labels, names, duplicate ids, tiny text, overflow), 14 widget interactions incl. keyboard and reduced motion |

## Conventions

- One assertion theme per test; names read as sentences (`test_impersonating_admin_cannot_switch_role`).
- A defect gets a **failing test first**, tagged in the commit and in `docs/QA_FINDINGS.md` (`QA-nnn`). While it is open the test is `xfail(strict=True)`; the fix flips it. Today no strict xfails remain.
- Never assert on flash wording when a status or a database row can prove the behaviour; when wording *is* the behaviour (login errors), assert on it deliberately.
- Tests write through the app where possible and through `db()` (sqlite helper fixture) only to arrange or verify.
- Keep `app.py` edits line-local; tests anchor on behaviour, not on line numbers.

## Adding a route

1. Add the handler.
2. Run the suite: `test_route_matrix.py` fails because the endpoint has no `POLICY` row. Add one (`OK`, `DENY`, `JSON`, `FILE`, …) per persona; add `MAY_DENY` entries where two outcomes are legitimate.
3. If it renders a template, add a `CASES` row in `test_render.py`, and the template name to `PAGE_TEMPLATES`/`MIGRATED`.
4. Any `<form method="post">` gets `<input type="hidden" name="csrf_token" …>` (the render and CSRF tests enforce it); fetches go through `HKC.fetchJSON` or send `X-CSRF-Token`.
5. Document the API endpoint in `templates/api_docs.html` (`test_api_docs_only_lists_endpoints_that_exist` keeps the docs honest).

## Coverage

| module | current | target |
|---|---|---|
| `app.py` | 79 % | ≥ 70 % |
| `security.py` | 92 % | ≥ 90 % |
| `csrf.py` | 100 % | ≥ 90 % |
| `db_init.py` | 98 % | ≥ 90 % |
| `storage.py` | 100 % | ≥ 90 % |

Uncovered `app.py` lines are mostly report CSV writers, the Excel import edge paths and the `__main__` block.

## Browser checklist (manual, when the scripted pass cannot judge)

- Light and dark at 375 / 768 / 1280: hierarchy readable, nothing clipped, no horizontal scroll.
- Keyboard only: skip link → header → nav → menus (Enter/Space open, arrows move, Escape closes and returns focus) → dialogs (focus trapped, Escape closes) → tabs (arrows) → forms (visible focus ring).
- Screen reader tree: one `h1`, landmarks (`header`, `nav`, `main`, `footer`), every control named, live region announces toasts.
- States: empty lists, long titles, 100+ rows (admin pagination), stacked flash messages, inactive user login, expired CSRF token (form resubmission after `LMS_SECRET_KEY` change).
- Reduced motion / transparency / contrast via OS settings: no transforms, solid chrome, stronger hairlines.
