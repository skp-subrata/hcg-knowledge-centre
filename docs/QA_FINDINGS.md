# QA findings

Log of defects found while testing `dev-akash`. Every row links to the test that pins it. Status values: `open`, `xfail` (a strict expected-failure test exists), `fixed` (fixed on this branch, test now passes), `report-only` (documented in `IMPROVEMENT_PLAN.md`, not fixed here), `accepted` (intended behaviour, decision recorded).

Severity: **S1** blocker or security, **S2** major (wrong result, data integrity), **S3** minor, **S4** cosmetic.

| id | area | type | sev | persona | steps | expected | actual | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| QA-001 | API v1 masters | logic | S1 | any API key | `POST /api/v1/departments` (also `/positions`, `/locations`) with `{"name": "X"}` | 201 | 500 `NameError: g` (also: routes are registered after `create_app()` and require API headers although the admin page calls them with a session) | `app.py` module-level routes after `app = create_app()`; `test_route_matrix` xfail | xfail |
| QA-002 | API v1 rewards | logic | S1 | any API key | `GET /api/v1/leaderboard` | 200 list | 500 `no such table: wallets` (table is `user_wallets`) | `api_get_leaderboard`; `test_route_matrix` xfail | xfail |
| QA-003 | API v1 courses | logic | S1 | any API key, no browser session | `GET /api/v1/courses/<id>`, `POST /api/v1/courses/<id>/assign` | 200 / 201 | 500 `KeyError: 'user_id'` (reads `session` under API-key auth; works only from the browser playground) | `api_get_course`, `api_assign_course`; `test_route_matrix` xfail incl. unknown-id pass | xfail |
| QA-004 | interests API | security | S2 | anonymous | `POST /api/interests {"interest_name": "x"}` | 401 | 500 `NameError: g`; with any session the row is created (no role check) | `create_interest`; `test_route_matrix` xfail | xfail |
| QA-012 | embed proxy | security | S1 | anonymous | `GET /proxy/embed?url=<any>` | login required, http(s) only, course URLs only | 200: fetches any URL (incl. `file://`, private hosts) and strips X-Frame-Options / CSP | `proxy_embed`; `test_route_matrix` xfail | xfail |
| QA-013 | uploads | security | S1 | anonymous | `GET /uploads/<file>` | login required; non-media as attachment | 200 inline for anyone who knows the name | `uploaded_file`; `test_route_matrix` xfail | xfail |
| QA-014 | interests API | privacy | S3 | anonymous | `GET /api/users/<id>/interests` | 401 | 200 (enumerable per user id) | `get_user_interests`; `test_route_matrix` xfail | xfail |
| QA-015 | routing | logic | S3 | staff | `GET /admin/reports` | one handler | registered twice (`admin_reports` staff, `reports` admin); second is dead code | `test_smoke::test_no_duplicate_url_rules` xfail | xfail |
| QA-017 | API v1 community | logic | S1 | any API key | `POST /api/v1/posts/<id>/comment {"comment": "x"}` | 201 | 500: inserts column `comment`, real column is `comment_text` | `api_comment_post`; `test_route_matrix` xfail | xfail |

## Decisions needed (public routes seen by the matrix)

| route | current | proposal |
|---|---|---|
| `GET /api/departments`, `GET /api/v1/departments` | anonymous 200 | keep public (dropdown data, no personal data) |
| `GET /api/interests` | anonymous 200 | keep public (master data) |
| `GET /api/v1/releases/active` | anonymous 200 | keep public (release notes) |
| `GET /api/notifications/unread` | anonymous 200 `{count: 0}` | keep (returns nothing for anonymous) |
| `GET /proxy/embed`, `GET /uploads/<file>`, `GET /api/users/<id>/interests` | anonymous 200 | require login (QA-012, QA-013, QA-014) |

## Predicted, to be confirmed by flow tests

Route-level smoke cannot see these; each gets a flow test in Phase 2.

| id | area | claim | evidence |
|---|---|---|---|
| QA-005 | admin delete | `POST /admin/delete/module/<id>` → 500 (`modules` table never exists) | `delete_record` allow-list |
| QA-006 | rewards admin | `POST /admin/rewards/source/update` with an unknown `calculation_type`/`status` → 500 (CHECK constraint, no validation) | `admin_update_reward_source` |
| QA-007 | rewards admin | adjust/settle with unknown or non-numeric `user_id` → 500 | `admin_adjust_rewards`, `admin_settle_rewards` |
| QA-008 | assessments | blank `pass_percentage`/`marks` stored as `''` → later `TypeError`/`ValueError` 500 | `add_assessment`, `add_question`, `assessment()` |
| QA-009 | courses | `duration_minutes=abc` → 500 | `courses_create` |
| QA-010 | groups | non-integer or unknown ids in member/assign/upload forms → 500 | group routes |
| QA-011 | API v1 | non-integer `rating` / `points` → 500 instead of 400 | `api_rate_post`, `api_settle_rewards`, `api_adjust_rewards` |
| QA-016 | impersonation | admin impersonating a user can `GET /switch-role` → `role=admin` under the victim's `user_id`; moderator can mint/read an admin's API key via `/admin` | `view_as`, `switch_role`, `admin_panel` |
| QA-018 | assessments | `max_attempts` never enforced on the web path (API enforces it) | `assessment()` |
| QA-019 | certification | passing only the 1-question `pre` assessment certifies (feedback uses MAX over all assessments); API submit never writes `course_certifications` | `feedback_form`, `api_submit_assessment` |
| QA-020 | rewards | web and API ledgers use opposite signs for settlements/resets; API adjust stores `abs()`; two reward reference key spaces → double pay | reward admin routes, API reward routes |
| QA-021 | auth | inactive users can log in and keep API access; API-created mixed-case usernames can never log in | `home()`, `api_required`, `api_create_user` |
| QA-022 | community | post body rendered with `\|safe` and notification text via `innerHTML` → stored XSS; attachments accept any file type | templates, `create_post`/`edit_post`, `base.html` |
| QA-023 | community | reviewer can approve own post; approvals allowed from any state; staff can rate DRAFT posts and earn rewards | `approval_action`, `rate_post` |
| QA-024 | groups/reports | dead status `'completed'` makes dashboard assessments, group completed counts and top-learner reports wrong | `home()`, `group_detail`, `admin_reports` |
