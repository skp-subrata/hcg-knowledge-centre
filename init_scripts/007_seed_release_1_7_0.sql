-- 007: bump the active release to 1.7.0. Deactivates every prior row so exactly one stays
-- active, matching the invariant tests/test_db_init.py enforces.

UPDATE app_releases SET is_active = 0;

INSERT OR IGNORE INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active) VALUES
    ('1.7.0', '1.7.0: A calmer, safer Knowledge Centre',
     '["A redesigned interface across every page: one calm light-and-dark design, clearer typography, and consistent cards, tables and forms.", "A short guided tour introduces the navigation, notifications, theme switch and account menu the first time you sign in.", "Release notes like these now open automatically the first time you sign in after an update, instead of waiting to be noticed."]',
     '["CSRF protection on every form and background request, session cookies hardened for HTTPS deployments.", "Faster restarts: the demo dataset is no longer re-hashed on every start-up.", "Dozens of correctness fixes across assessments, certificates, rewards and the community feed, each backed by an automated test.", "One-command setup (`run.sh` / `run.ps1`) with guided deployment docs for Render and PythonAnywhere."]',
     '["Fixed a startup crash on a fresh checkout when the uploads folder did not yet exist.", "Fixed inconsistent reward ledger totals between the web and API paths.", "Fixed assessments allowing unlimited retakes and a pre-assessment loophole that could certify a course early."]',
     1);
