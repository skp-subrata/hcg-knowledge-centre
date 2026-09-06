# QA findings

Log of defects found while testing `dev-akash`. Every row links to the test that pins it. Status values: `open`, `xfail` (a strict expected-failure test exists), `fixed` (fixed on this branch, test now passes), `report-only` (documented in `IMPROVEMENT_PLAN.md`, not fixed here), `accepted` (intended behaviour, decision recorded).

Severity: **S1** blocker or security, **S2** major (wrong result, data integrity), **S3** minor, **S4** cosmetic.

| id | area | type | sev | persona | steps | expected | actual | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| QA-001 | API v1 masters | logic | S1 | any API key | `POST /api/v1/departments` (also `/positions`, `/locations`) with `{"name": "X"}` | 201 | 500 `NameError: g` (also: routes are registered after `create_app()` and require API headers although the admin page calls them with a session) | `app.py` module-level routes after `app = create_app()`; `test_route_matrix` xfail | fixed |
| QA-002 | API v1 rewards | logic | S1 | any API key | `GET /api/v1/leaderboard` | 200 list | 500 `no such table: wallets` (table is `user_wallets`) | `api_get_leaderboard`; `test_route_matrix` xfail | fixed |
| QA-003 | API v1 courses | logic | S1 | any API key, no browser session | `GET /api/v1/courses/<id>`, `POST /api/v1/courses/<id>/assign` | 200 / 201 | 500 `KeyError: 'user_id'` (reads `session` under API-key auth; works only from the browser playground) | `api_get_course`, `api_assign_course`; `test_route_matrix` xfail incl. unknown-id pass | fixed |
| QA-004 | interests API | security | S2 | anonymous | `POST /api/interests {"interest_name": "x"}` | 401 | 500 `NameError: g`; with any session the row is created (no role check) | `create_interest`; `test_route_matrix` xfail | fixed |
| QA-012 | embed proxy | security | S1 | anonymous | `GET /proxy/embed?url=<any>` | login required, http(s) only, course URLs only | 200: fetches any URL (incl. `file://`, private hosts) and strips X-Frame-Options / CSP | `proxy_embed`; `test_route_matrix` xfail | fixed (login + course URL + public-address check; iframe sandbox no longer same-origin; tests/test_security.py) |
| QA-013 | uploads | security | S1 | anonymous | `GET /uploads/<file>` | login required; non-media as attachment | 200 inline for anyone who knows the name | `uploaded_file`; `test_route_matrix` xfail | fixed (login required; non-media served as attachment with nosniff) |
| QA-014 | interests API | privacy | S3 | anonymous | `GET /api/users/<id>/interests` | 401 | 200 (enumerable per user id) | `get_user_interests`; `test_route_matrix` xfail | fixed (login required) |
| QA-015 | routing | logic | S3 | staff | `GET /admin/reports` | one handler | registered twice (`admin_reports` staff, `reports` admin); second is dead code | `test_smoke::test_no_duplicate_url_rules` xfail | fixed (dead reports() route removed; tests/test_smoke.py) |
| QA-017 | API v1 community | logic | S1 | any API key | `POST /api/v1/posts/<id>/comment {"comment": "x"}` | 201 | 500: inserts column `comment`, real column is `comment_text` | `api_comment_post`; `test_route_matrix` xfail | fixed |

## Decisions needed (public routes seen by the matrix)

| route | current | proposal |
|---|---|---|
| `GET /api/departments`, `GET /api/v1/departments` | anonymous 200 | keep public (dropdown data, no personal data) |
| `GET /api/interests` | anonymous 200 | keep public (master data) |
| `GET /api/v1/releases/active` | anonymous 200 | keep public (release notes) |
| `GET /api/notifications/unread` | anonymous 200 `{count: 0}` | keep (returns nothing for anonymous) |
| `GET /proxy/embed`, `GET /uploads/<file>`, `GET /api/users/<id>/interests` | login required (fixed) | done |

## Predicted, to be confirmed by flow tests

Route-level smoke cannot see these; each gets a flow test in Phase 2.

| id | area | claim | evidence |
|---|---|---|---|
| QA-005 | admin delete | `POST /admin/delete/module/<id>` → 500 (`modules` table never exists) | `delete_record` allow-list → **fixed** (phantom 'module' resource removed; tests/test_admin.py) |
| QA-006 | rewards admin | `POST /admin/rewards/source/update` with an unknown `calculation_type`/`status` → 500 (CHECK constraint, no validation) | `admin_update_reward_source` → **fixed** (status/calculation_type validated; tests/test_validation.py) |
| QA-007 | rewards admin | adjust/settle with unknown or non-numeric `user_id` → 500 | `admin_adjust_rewards`, `admin_settle_rewards` → **fixed** (tests/test_rewards.py) |
| QA-008 | assessments | blank `pass_percentage`/`marks` stored as `''` → later `TypeError`/`ValueError` 500 | `add_assessment`, `add_question`, `assessment()` → **fixed** (int_or() for pass %, attempts and marks; option validated; tests/test_assessments.py) |
| QA-009 | courses | `duration_minutes=abc` → 500 | `courses_create` → **fixed** (int_or for duration_minutes) |
| QA-010 | groups | non-integer or unknown ids in member/assign/upload forms → 500 | group routes → **fixed** (API-credential target parsed safely; group member/course ids already guarded by the routes' try/except - remaining edge cases noted in the report) |
| QA-011 | API v1 | non-integer `rating` / `points` → 500 instead of 400 | `api_rate_post`, `api_settle_rewards`, `api_adjust_rewards` → **fixed** (tests/test_rewards.py, API reward routes) |
| QA-016 | impersonation | admin impersonating a user can `GET /switch-role` → `role=admin` under the victim's `user_id`; moderator can mint/read an admin's API key via `/admin` | `view_as`, `switch_role`, `admin_panel` → **fixed** (tests/test_security.py: API keys admin-only, actual_role follows impersonation, no role switch while impersonating) |
| QA-018 | assessments | `max_attempts` never enforced on the web path (API enforces it) | `assessment()` → **fixed** (web assessment() enforces max_attempts) |
| QA-019 | certification | passing only the 1-question `pre` assessment certifies (feedback uses MAX over all assessments); API submit never writes `course_certifications` | `feedback_form`, `api_submit_assessment` → **fixed** (only post-assessment passes certify; API submit writes course_certifications; one certificate per learner/course (006)) |
| QA-020 | rewards | web and API ledgers use opposite signs for settlements/resets; API adjust stores `abs()`; two reward reference key spaces → double pay | reward admin routes, API reward routes → **fixed** (tests/test_rewards.py; both surfaces now share one ledger convention) |
| QA-021 | auth | inactive users can log in and keep API access; API-created mixed-case usernames can never log in | `home()`, `api_required`, `api_create_user` → **fixed** (login and api_required check is_active; API usernames lower-cased) |
| QA-022 | community | post body rendered with `\|safe` and notification text via `innerHTML` → stored XSS; attachments accept any file type | templates, `create_post`/`edit_post`, `base.html` → **fixed** (attachment allowlist; post bodies sanitised on write and on render with an allow-list sanitiser; notification text escaped in the header script; tests/test_community.py) |
| QA-023 | community | reviewer can approve own post; approvals allowed from any state; staff can rate DRAFT posts and earn rewards | `approval_action`, `rate_post` → **fixed** (self-review blocked; reviews only from PENDING_APPROVAL/UNPUBLISHED; only PUBLISHED posts can be rated on web and API) |
| QA-024 | groups/reports | dead status `'completed'` makes dashboard assessments, group completed counts and top-learner reports wrong | `home()`, `group_detail`, `admin_reports` → **fixed** (dashboard/group/top-learner queries no longer depend on the dead 'completed' status) |
| QA-025 | admin | `/api/admin/assessments` omitted `pass_percentage` and `max_attempts`, so the admin table (which re-renders from it) and the inline edit form showed blank pass marks and attempt limits | `api_admin_assessments` → **fixed** (columns added; tests/test_admin.py::test_admin_assessments_api_returns_pass_mark_and_attempts) |
| QA-026 | a11y | Quill toolbar buttons and pickers have no accessible names; the hidden `description` textarea and the link-URL input are exposed unlabelled; `admin.html` reused the sheet title id for the assessment title field (duplicate id, label not associated) | create/edit post, admin → **fixed** (`HKC.labelQuillToolbar`, `aria-hidden` on the mirror textarea, field id renamed; qa/browser_qa.py a11y check) |
| QA-027 | error handling | 404/405/413 responses were Flask's unstyled defaults; `/api/...` callers got HTML | all routes → **fixed** (`error.html` on the shared layout for browsers, JSON for `/api/*` and AJAX; tests/test_render.py::test_error_page_renders_on_the_new_base) |
| QA-028 | admin UX | Editing any seeded user fails validation until email, employee id and phone are filled in, because `update_user` requires them but the demo data has none — an admin cannot change just the role or department of a legacy user | `update_user` → **open (report)**: relax mandatory contact fields on update, or backfill contact data during seeding |
| QA-029 | front-end | Tailwind is loaded from the play CDN and warns in every console; Quill/Chart.js/html2canvas also come from CDNs without SRI pins | `base.html` → **open (report)**: vendor the assets or add a build step before an intranet deployment |
| QA-030 | browser QA | Headless Chromium logs `No available adapters` on the Video course page (no proprietary codecs in the test browser); the page itself renders correctly | course page → **not a defect**: environment noise, documented in docs/qa/browser_report.md |
