-- 005: Release notes shown by the version badge / "What's new" sheet.
-- Text taken from the previously hard-coded release modal and migrate_db_versions.py.
-- features / improvements / bug_fixes are JSON arrays of strings. Exactly one row is active.

INSERT OR IGNORE INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active) VALUES
    ('1.6.1', '1.6.1 Release',
     '["Post Inactivation & Rating Safety: safely remove your posts from the public forum without data loss; self-rating is prevented.", "Group Department Filter: the Department filter on Group Management now reads live data from the Department master."]',
     '["Edit User modal now submits via AJAX: it stays open, shows inline success or error messages, and the user table refreshes without a full reload.", "Context-aware navigation: errors and restrictions return you to your previous screen instead of Home."]',
     '[]',
     1),
    ('1.5.0', '1.5.0 Release',
     '["Interactive Profile Customization with Interest Chips", "Dynamic Release Notes Engine"]',
     '["Streamlined Add User Admin Workflow", "Restored Edit User Popup Wizard", "Added Employee ID to Tables"]',
     '["Fixed template syntax error on Admin panel"]',
     0),
    ('1.4.0', '1.4.0 Release',
     '["Strict visibility: draft and inactive courses are hidden from students.", "Embedded webpages: external website courses are embedded inline through a security proxy.", "Image thumbnails auto-scale to keep their aspect ratio."]',
     '[]',
     '[]',
     0),
    ('1.3.2', '1.3.2 Release',
     '["Content Creation & Social Feed: share, rate and comment on articles, PDFs, videos and PPTs, with an approval queue and draft management.", "Reward Management Ledger: configurable points rules, settlements, manual adjustments and auditable resets.", "Activity Reports & Analytics: downloadable CSV reports for content, approvals, engagement and rewards."]',
     '["Course detail pages with side-by-side feedback tracking, client-side dashboard filtering, refined notification chime, role-based access to API developer tools."]',
     '["Fixed SQLite check-constraint errors during draft creation.", "Resolved a Jinja TypeError on community feed rating rounding.", "Replaced page-level alerts with a global impersonation banner and exit shortcut."]',
     0);
