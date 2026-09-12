-- 014: bump the active release to 1.9.0. Deactivates every prior row so exactly one stays
-- active, matching the invariant tests/test_db_init.py enforces.

UPDATE app_releases SET is_active = 0;

INSERT OR IGNORE INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active) VALUES
    ('1.9.0', '1.9.0: Real support tickets, engagement analytics, and a Boomi course',
     '["Ask for help without needing GitHub: the floating feedback button now creates a real, trackable support ticket, with your name captured automatically -- no GitHub account required.", "System & activity now shows real engagement analytics: total unique users, weekly and daily-average active users, usage trend charts, and a breakdown of who is engaging by department and office location.", "A new course: Boomi Integration Platform Fundamentals, with a 5-question assessment.", "Certificates can now be downloaded as a PDF, not just PNG."]',
     '["Certificate downloads (PNG and PDF) now always match what you see on screen, regardless of your browser window size when you click download.", "The tier badge (Platinum, Gold, Silver, Bronze) now actually shows up in downloaded certificates.", "\"View as another user\" only appears in the account menu while you are actually in your Admin workspace, not while browsing as a student.", "Pages that embed external content now show a clear message with a link to open it directly, instead of a blank box, when they cannot be displayed here.", "New quick-feedback categories (Bug Report, Feature Request, General Feedback) for tickets filed from the floating feedback button."]',
     '["Fixed a redirect loop after submitting course feedback that could show \"too many redirects\" instead of your certificate.", "Fixed several dividers rendering as a full box instead of a single line (certificate stats, group details, the navigation drawer, and more).", "Fixed a crash risk in the group-sync process if a group member''s account no longer exists.", "Fixed the Assign-a-course learner picker not finding newly created users."]',
     1);
