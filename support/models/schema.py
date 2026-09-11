"""
Support Module Database Schema DDL.
Creates all support_* database tables, indexes, and seeds default categories.
Completely isolated from primary application tables.
"""

from support.config import INITIAL_CATEGORIES, ADDITIONAL_CATEGORIES


def init_support_db(connection):
    """
    Execute DDL to create support module tables and indexes if they do not exist.
    """
    with connection:
        # 1. Support Categories Master
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'Active' CHECK (status IN ('Active', 'Inactive')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed initial categories if empty
        cat_count = connection.execute("SELECT COUNT(*) AS count FROM support_categories").fetchone()["count"]
        if cat_count == 0:
            for name, code, desc in INITIAL_CATEGORIES:
                connection.execute(
                    "INSERT OR IGNORE INTO support_categories (name, code, description) VALUES (?, ?, ?)",
                    (name, code, desc)
                )

        # Seed the feedback-widget categories unconditionally (not gated behind cat_count == 0):
        # this runs on every app start, so it also back-fills a database that already seeded
        # INITIAL_CATEGORIES before these existed. UNIQUE(code) + INSERT OR IGNORE make repeats free.
        for name, code, desc in ADDITIONAL_CATEGORIES:
            connection.execute(
                "INSERT OR IGNORE INTO support_categories (name, code, description) VALUES (?, ?, ?)",
                (name, code, desc)
            )

        # 2. Support Issues Core Table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_issues (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_number TEXT NOT NULL UNIQUE,
                reported_by_user_id INTEGER NOT NULL REFERENCES users(id),
                reporter_name TEXT NOT NULL,
                reporter_employee_id TEXT DEFAULT '',
                reporter_email TEXT DEFAULT '',
                reporter_phone TEXT DEFAULT '',
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES support_categories(id),
                priority TEXT DEFAULT 'Medium' CHECK (priority IN ('Critical', 'High', 'Medium', 'Low')),
                status TEXT DEFAULT 'REPORTED' CHECK (status IN (
                    'REPORTED', 'UNDER_REVIEW', 'IN_PROGRESS', 'RESOLUTION_PROVIDED',
                    'AWAITING_CONFIRMATION', 'RESOLVED_CONFIRMED', 'REOPENED', 'CLOSED'
                )),
                module_name TEXT DEFAULT '',
                page_url TEXT DEFAULT '',
                device_info TEXT DEFAULT '',
                browser_info TEXT DEFAULT '',
                os_info TEXT DEFAULT '',
                assigned_to_user_id INTEGER REFERENCES users(id),
                resolution_summary TEXT DEFAULT '',
                resolution_details TEXT DEFAULT '',
                reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                under_review_at DATETIME,
                in_progress_at DATETIME,
                resolution_provided_at DATETIME,
                awaiting_confirmation_at DATETIME,
                resolved_confirmed_at DATETIME,
                reopened_at DATETIME,
                closed_at DATETIME,
                first_response_at DATETIME,
                resolved_at DATETIME,
                resolution_confirmed_by_user_id INTEGER REFERENCES users(id),
                source_application TEXT DEFAULT 'LMS',
                is_archived INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER REFERENCES users(id),
                updated_by INTEGER REFERENCES users(id)
            )
        """)

        # Indexes for support_issues
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_number ON support_issues(issue_number)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_reporter ON support_issues(reported_by_user_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_status ON support_issues(status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_priority ON support_issues(priority)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_category ON support_issues(category_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_created ON support_issues(created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_issues_assigned ON support_issues(assigned_to_user_id)")

        # 3. Support Issue Updates / Timeline History Table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_issue_updates (
                update_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL REFERENCES support_issues(issue_id) ON DELETE CASCADE,
                updated_by_user_id INTEGER NOT NULL REFERENCES users(id),
                update_type TEXT NOT NULL CHECK (update_type IN (
                    'COMMENT', 'STATUS_CHANGE', 'PRIORITY_CHANGE', 'ASSIGNMENT',
                    'RESOLUTION', 'REOPENED', 'USER_CONFIRMATION', 'USER_REJECTION', 'SYSTEM'
                )),
                message TEXT DEFAULT '',
                old_status TEXT,
                new_status TEXT,
                old_priority TEXT,
                new_priority TEXT,
                is_internal INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_updates_issue ON support_issue_updates(issue_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_updates_created ON support_issue_updates(created_at)")

        # 4. Support Issue Attachments Table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_issue_attachments (
                attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL REFERENCES support_issues(issue_id) ON DELETE CASCADE,
                update_id INTEGER REFERENCES support_issue_updates(update_id),
                uploaded_by_user_id INTEGER NOT NULL REFERENCES users(id),
                original_file_name TEXT NOT NULL,
                stored_file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_url TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_extension TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                storage_provider TEXT DEFAULT 'LOCAL',
                status TEXT DEFAULT 'Active' CHECK (status IN ('Active', 'Deleted')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_attachments_issue ON support_issue_attachments(issue_id)")

        # 5. Support Audit Logs Table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_audit_logs (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER REFERENCES support_issues(issue_id),
                performed_by_user_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("CREATE INDEX IF NOT EXISTS idx_support_audit_issue ON support_audit_logs(issue_id)")

