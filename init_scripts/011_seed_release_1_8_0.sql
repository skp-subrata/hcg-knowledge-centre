-- 011: bump the active release to 1.8.0. Deactivates every prior row so exactly one stays
-- active, matching the invariant tests/test_db_init.py enforces.

UPDATE app_releases SET is_active = 0;

INSERT OR IGNORE INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active) VALUES
    ('1.8.0', '1.8.0: Compulsory courses, smarter groups, deeper reports',
     '["Compulsory courses: mark a course compulsory and it is automatically assigned to everyone the moment it is published, and to every new person who joins afterwards.", "Smarter groups: Department and Location groups, plus a company-wide All Users group, are now created and kept in sync automatically -- no more manual list-building.", "A deeper Reports & Analytics dashboard: filter by date range or a quick preset (today, 7/30/90 days, this year), with new charts for assignment progress, community activity, reward points and support tickets.", "Real profile pictures wherever people appear: community posts and comments, course feedback, group members, and the admin panel now show your actual photo instead of just initials."]',
     '["Certificates look the part again: each tier (Platinum, Gold, Silver, Bronze) now has its own distinct colour and glow, in both light and dark mode.", "Admins can set a user''s profile picture directly from the Admin panel, not just from their own Profile page.", "The ten existing CSV export reports (content, engagement, assessments, rewards and more) are now easy to find and download right from the Reports page."]',
     '["Fixed the course-certificate download looking flat, with no real difference between certificate tiers.", "Fixed the certificate page never actually looking different in dark mode."]',
     1);
