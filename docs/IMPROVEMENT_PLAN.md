# Improvement plan

Where HCG Knowledge Centre stands after the `dev-akash` work, and where it should go next. Evidence links point at tests (`tests/…`), QA findings (`docs/QA_FINDINGS.md`, ids `QA-nnn`) and the route matrix (`docs/ROUTE_ROLE_MATRIX.md`).

## Executive summary

`dev-akash` turns a single-developer prototype into something a team can run, test and change safely:

- **Fresh installs work.** Versioned SQL init scripts create every table the code needs; `./run.sh` bootstraps a machine in one command (`tests/test_db_init.py`, `README.md`).
- **The suite is the safety net.** 840 tests cover every route for eight personas (zero 5xx responses, no anonymous access outside the agreed public list), the learner journey, staff authoring, community, groups, rewards, the API, security and CSRF. It runs in about five seconds.
- **Confirmed defects are fixed and pinned.** Thirty findings are logged; twenty-six are fixed with a test each. The remaining four are report-only decisions for the product owner (see *Open decisions*).
- **The UI is one system.** Twenty-seven templates were rebuilt on a token-based design system (light/dark, reduced motion, keyboard and screen-reader support), verified by a scripted browser pass over 30 pages and 14 interactions.

The biggest remaining risks are **product-level**: two overlapping certification systems, no due dates or manager tracking, and no audit trail. Those need design decisions, not just code.

## Scorecard

| Dimension | Before | After | Rationale |
|---|---|---|---|
| Logic correctness | 2 / 5 | 4 / 5 | 45 defects fixed (API 500s, ledger signs, assessment rules, certificates). Two certification systems still coexist (S1 below). |
| UI / UX | 2 / 5 | 4 / 5 | One design system, responsive at 375/768/1280, dark mode, dialogs with focus management. Remaining: no empty-state onboarding for a brand-new tenant, carousel autoplay kept on request. |
| Security & privacy | 1 / 5 | 4 / 5 | Auth escalations, SSRF, stored XSS, unauthenticated uploads, CSRF fixed; secrets persisted; cookies hardened. API secrets still stored in plaintext (decision needed). |
| Business fit | 2 / 5 | 3 / 5 | Core L&D loop works end to end. Missing: due dates, mandatory training, manager view, learning paths, integrity controls. |
| Code health | 1 / 5 | 3 / 5 | Junk removed, tests and docs added, security helpers extracted. `app.py` remains a 5,200-line `create_app()`; splitting it is the next structural step. |

## Priorities

Effort: **S** < 1 day, **M** 1–3 days, **L** > 3 days.

### P0 — do before the next release

| id | item | evidence | recommendation | effort |
|---|---|---|---|---|
| P0-1 | One certification model | `certificates` and `course_certifications` both record certification; the API and web paths were writing different tables until QA-019 | Make `course_certifications` the single source of truth; derive certificates from it; migrate and drop the duplicate columns | M |
| P0-2 | Hash API secrets | `api_credentials.api_secret` is plaintext and shown in the admin table | Store `sha256(secret)`, reveal the secret once at generation, add an idempotent migration keyed on the `as_` prefix | S |
| P0-3 | Mandatory-field rule on user update blocks legacy users | QA-028 | Require contact fields on create only, or backfill demo data | S |
| P0-4 | Vendor front-end assets | QA-029; Tailwind play CDN warns in every console, no SRI on Quill/Chart.js/html2canvas | Add a build step (Tailwind CLI) or vendor pinned files under `static/vendor/` for intranet deployments | S |

### P1 — next quarter

| id | item | evidence | recommendation | effort |
|---|---|---|---|---|
| P1-1 | Due dates, overdue state, reminders | `course_assignments` has no due date; notifications only fire on events | Add `due_at`, an overdue badge on cards, a daily reminder job | M |
| P1-2 | Manager / team view | Groups exist but there is no "my team's progress" page for a manager | Group-scoped progress view reusing `group_detail` queries; CSV export | M |
| P1-3 | Audit trail | Impersonation, role switches, deletions and reward adjustments are not attributed | `audit_log(actor_id, impersonator_id, action, target, at)` written from a small helper; admin page | M |
| P1-4 | Assessment integrity | Questions are served in a fixed order with no time limit; the question bank tables are unused by the UI | Shuffle, optional time limit, pool size, question banks in the wizard | M |
| P1-5 | Learning paths & prerequisites | Courses are flat | `learning_paths` with ordered courses; lock the next until the previous is certified | L |
| P1-6 | Mandatory / compliance flag | No way to mark training as required | `courses.is_mandatory`, dashboards and reports filter on it | S |
| P1-7 | Search and discovery | Catalogue search is client-side over the loaded page | Server-side search with category/level facets; the `data-filter` UI already exists | S |
| P1-8 | Split `app.py` | 5,200 lines, one factory, closures everywhere | Blueprints per area (auth, courses, assessments, community, rewards, admin, api); move shared helpers (`create_notification`, `int_or`) to modules | L |
| P1-9 | Password policy & lockout | Any 6-character password is accepted; no rate limiting on `/` | Minimum length + complexity, lockout after N failures, `Secure` cookie flag behind HTTPS | S |
| P1-10 | Notifications outside the app | Only in-app; every `create_notification` failure is swallowed | Email/Slack adapter behind the same helper; log failures instead of `except: pass` | M |

### P2 — later

| id | item | recommendation | effort |
|---|---|---|---|
| P2-1 | Certificate expiry and renewal | `valid_until` on certifications; renewal assignments | M |
| P2-2 | Content versioning | Snapshot course content on publish; learners see the version they were assigned | L |
| P2-3 | SSO (SAML/OIDC) | Replace the local password table for staff; keep local login for demo | L |
| P2-4 | Release notes admin UI | `app_releases` is DB-driven now but only editable via SQL | S |
| P2-5 | Positions and interests masters UI | Tables exist; only departments and locations have screens | S |
| P2-6 | Mobile polish | Sticky action bars for long forms, larger tap targets in tables | S |

### P3 — strategic

| id | item |
|---|---|
| P3-1 | Multi-tenancy (per-business-unit isolation) |
| P3-2 | Analytics warehouse export (attempts, completions, rewards) |
| P3-3 | Public API v2 with OAuth client credentials replacing static keys |

## Quick wins vs. strategic

**Quick wins (≤ 1 day each):** P0-2, P0-3, P0-4, P1-6, P1-7, P1-9, P2-4, P2-5.
**Strategic (need design decisions):** P0-1, P1-5, P1-8, P2-2, P2-3, P3-*.

## Roadmap

1. **R1 "Safe"** — ship `dev-akash`, then P0-1…P0-4. Exit: no plaintext secrets, one certification source, assets served locally, suite green.
2. **R2 "Trustworthy"** — P1-1, P1-2, P1-3, P1-9, P1-10. Exit: managers can see overdue training, every privileged action is attributed, learners are reminded.
3. **R3 "Complete"** — P1-4, P1-5, P1-6, P1-7, P1-8, P2-*. Exit: paths, integrity controls, blueprints, SSO.

## Open decisions for the product owner

| topic | options | recommendation |
|---|---|---|
| Certificate wording | "HCG Academy" (current) vs "HCG Knowledge Centre" | Align with the product name |
| Dashboard carousel | autoplay kept as requested; pauses under reduced-motion | Consider three static cards; autoplay hides content from slow readers |
| API secret hashing | plaintext (copy anytime) vs hashed (reveal once) | Hash; the download-JSON action already covers the "copy later" need at generation time |
| Demo seeding in production | `LMS_SEED_DEMO=1` by default | Default to `0` in the deployment environment |
| `firebase-functions` dependency | unused by the app, pulls the Google Cloud stack | Remove from `requirements.txt` when the hosting plan is confirmed |

## Code smells worth scheduling

| id | smell | where | why it matters |
|---|---|---|---|
| S1 | Two certification tables | `certificates`, `course_certifications` | Reports and badges can disagree; fixed at the write sites, not structurally |
| S2 | Two reward reference key spaces | `reward_transactions.reference_id` used for posts and attempts | Double pay was possible (QA-020); a `reference_type` column would make it impossible |
| S3 | Status vocabularies | `draft/published` (courses), `PUBLISHED/PENDING_APPROVAL` (posts), `in_progress/certified` (assignments) | Case and naming differ per table; centralise as constants |
| S4 | Seeding on every start | `seed_demo_data()` at import | Slows start-up and tests; gated now, should be a CLI command only |
| S5 | Swallowed failures | `except Exception: pass` around notifications | Bugs disappear silently; log at least |
| S6 | Per-request context queries | unread count + active release on every page | Cache the release; keep the unread count |
| S7 | GET/POST mixed admin form | `/admin` handles 13 actions in one view | Blueprint + one route per action |
| S8 | Cookie-dependent API routes | masters endpoints accept session or API key | Fine for the playground; document it |
| S9 | Raw-marks payout | reward for an attempt is proportional to marks, not percentage | Course authors can inflate rewards with big mark values |
| S10 | Inline JS in templates | admin, api_docs, courses, profile | Acceptable now (no build step); move to `static/js/pages/` when a bundler arrives |

## What was delivered on `dev-akash`

- Bootstrap: `run.sh`, `db_init.py`, `init_scripts/000–006`, `flask init-db`, `LMS_*` configuration, README.
- Fixes: API v1 plumbing and semantics, rewards ledger, assessments and certificates, admin hygiene, authorization, hardening (SSRF, uploads, secret key, cookies), CSRF.
- Redesign: `static/css/app.css` tokens and components, `static/js/app.js` (`window.HKC`), `templates/_macros.html`, `_partials/`, every page template.
- Verification: 840 tests, route × role matrix, Playwright browser pass, QA log.
