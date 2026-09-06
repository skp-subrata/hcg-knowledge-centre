"""
Issue Repository.
Data access layer for support_issues, support_issue_updates, and support_issue_attachments.
"""

import math


def generate_next_issue_number(connection):
    """
    Generate next unique human-readable issue number, format: SUP-YYYY-000001
    """
    from datetime import datetime
    year = datetime.now().year
    prefix = f"SUP-{year}-"
    row = connection.execute(
        "SELECT MAX(issue_id) AS max_id FROM support_issues"
    ).fetchone()
    next_seq = (row["max_id"] or 0) + 1
    return f"{prefix}{next_seq:06d}"


def create_issue(connection, issue_data):
    """
    Insert a new support issue record and return its issue_id.
    """
    sql = """
        INSERT INTO support_issues (
            issue_number, reported_by_user_id, reporter_name, reporter_employee_id,
            reporter_email, reporter_phone, title, description, category_id, priority,
            status, module_name, page_url, device_info, browser_info, os_info,
            reported_at, source_application, created_by, updated_by
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'REPORTED', ?, ?, ?, ?, ?,
            CURRENT_TIMESTAMP, ?, ?, ?
        )
    """
    cursor = connection.execute(sql, (
        issue_data["issue_number"],
        issue_data["reported_by_user_id"],
        issue_data["reporter_name"],
        issue_data.get("reporter_employee_id", ""),
        issue_data.get("reporter_email", ""),
        issue_data.get("reporter_phone", ""),
        issue_data["title"],
        issue_data["description"],
        issue_data["category_id"],
        issue_data.get("priority", "Medium"),
        issue_data.get("module_name", ""),
        issue_data.get("page_url", ""),
        issue_data.get("device_info", ""),
        issue_data.get("browser_info", ""),
        issue_data.get("os_info", ""),
        issue_data.get("source_application", "LMS"),
        issue_data["reported_by_user_id"],
        issue_data["reported_by_user_id"]
    ))
    return cursor.lastrowid


def get_issue_by_id(connection, issue_id):
    """
    Fetch a single support issue by ID with joined category and user info.
    """
    sql = """
        SELECT i.*, 
               c.name AS category_name, c.code AS category_code,
               u.full_name AS current_reporter_name, u.email AS current_reporter_email,
               u.phone_number AS current_reporter_phone, u.employee_id AS current_reporter_emp_id,
               assignee.full_name AS assignee_name
        FROM support_issues i
        LEFT JOIN support_categories c ON c.id = i.category_id
        LEFT JOIN users u ON u.id = i.reported_by_user_id
        LEFT JOIN users assignee ON assignee.id = i.assigned_to_user_id
        WHERE i.issue_id = ?
    """
    return connection.execute(sql, (issue_id,)).fetchone()


def get_issue_by_number(connection, issue_number):
    """
    Fetch a single support issue by human-readable issue_number.
    """
    sql = """
        SELECT i.*, c.name AS category_name
        FROM support_issues i
        LEFT JOIN support_categories c ON c.id = i.category_id
        WHERE i.issue_number = ?
    """
    return connection.execute(sql, (issue_number,)).fetchone()


def get_user_issues(connection, user_id, page=1, page_size=15, search="", category_id=None, status_filter="", priority_filter=""):
    """
    Fetch paginated issues reported by a specific user.
    """
    offset = (page - 1) * page_size
    where_clauses = ["i.reported_by_user_id = ?", "i.is_archived = 0"]
    params = [user_id]

    if search:
        s_pat = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(i.issue_number) LIKE ? OR LOWER(i.title) LIKE ? OR LOWER(i.description) LIKE ?)")
        params.extend([s_pat, s_pat, s_pat])

    if category_id:
        where_clauses.append("i.category_id = ?")
        params.append(category_id)

    if status_filter:
        where_clauses.append("i.status = ?")
        params.append(status_filter)

    if priority_filter:
        where_clauses.append("i.priority = ?")
        params.append(priority_filter)

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) AS total FROM support_issues i {where_str}"
    total_records = connection.execute(count_sql, params).fetchone()["total"]

    data_sql = f"""
        SELECT i.*, c.name AS category_name,
               (SELECT COUNT(*) FROM support_issue_updates u WHERE u.issue_id = i.issue_id) AS update_count,
               (SELECT COUNT(*) FROM support_issue_attachments a WHERE a.issue_id = i.issue_id) AS attachment_count
        FROM support_issues i
        LEFT JOIN support_categories c ON c.id = i.category_id
        {where_str}
        ORDER BY i.updated_at DESC, i.issue_id DESC
        LIMIT ? OFFSET ?
    """
    data_params = params + [page_size, offset]
    rows = connection.execute(data_sql, data_params).fetchall()

    total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

    return {
        "data": [dict(r) for r in rows],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalRecords": total_records,
            "totalPages": total_pages
        }
    }


def get_admin_issues(connection, page=1, page_size=15, search="", category_id=None, status_filter="", priority_filter="", assigned_to=None):
    """
    Fetch paginated issues for Admin view with search and filters.
    """
    offset = (page - 1) * page_size
    where_clauses = ["i.is_archived = 0"]
    params = []

    if search:
        s_pat = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(i.issue_number) LIKE ? OR LOWER(i.title) LIKE ? OR LOWER(i.description) LIKE ? OR LOWER(i.reporter_name) LIKE ? OR LOWER(i.reporter_email) LIKE ? OR LOWER(i.reporter_employee_id) LIKE ?)")
        params.extend([s_pat, s_pat, s_pat, s_pat, s_pat, s_pat])

    if category_id:
        where_clauses.append("i.category_id = ?")
        params.append(category_id)

    if status_filter:
        where_clauses.append("i.status = ?")
        params.append(status_filter)

    if priority_filter:
        where_clauses.append("i.priority = ?")
        params.append(priority_filter)

    if assigned_to:
        where_clauses.append("i.assigned_to_user_id = ?")
        params.append(assigned_to)

    where_str = " WHERE " + " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) AS total FROM support_issues i {where_str}"
    total_records = connection.execute(count_sql, params).fetchone()["total"]

    data_sql = f"""
        SELECT i.*, c.name AS category_name, assignee.full_name AS assignee_name,
               (SELECT COUNT(*) FROM support_issue_updates u WHERE u.issue_id = i.issue_id) AS update_count
        FROM support_issues i
        LEFT JOIN support_categories c ON c.id = i.category_id
        LEFT JOIN users assignee ON assignee.id = i.assigned_to_user_id
        {where_str}
        ORDER BY 
            CASE i.priority 
                WHEN 'Critical' THEN 1 
                WHEN 'High' THEN 2 
                WHEN 'Medium' THEN 3 
                WHEN 'Low' THEN 4 
            END ASC,
            i.updated_at DESC
        LIMIT ? OFFSET ?
    """
    data_params = params + [page_size, offset]
    rows = connection.execute(data_sql, data_params).fetchall()

    total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

    return {
        "data": [dict(r) for r in rows],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalRecords": total_records,
            "totalPages": total_pages
        }
    }


def update_issue_status(connection, issue_id, new_status, updated_by_user_id, timestamp_field=None):
    """
    Update the status of an issue and optional lifecycle timestamp.
    """
    sql = "UPDATE support_issues SET status = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?"
    params = [new_status, updated_by_user_id]

    if timestamp_field:
        sql += f", {timestamp_field} = CURRENT_TIMESTAMP"

    sql += " WHERE issue_id = ?"
    params.append(issue_id)

    connection.execute(sql, params)


def update_issue_priority(connection, issue_id, new_priority, updated_by_user_id):
    """
    Update priority of an issue.
    """
    connection.execute(
        "UPDATE support_issues SET priority = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ? WHERE issue_id = ?",
        (new_priority, updated_by_user_id, issue_id)
    )


def update_issue_assignment(connection, issue_id, assigned_to_user_id, updated_by_user_id):
    """
    Assign issue to support staff/developer.
    """
    connection.execute(
        "UPDATE support_issues SET assigned_to_user_id = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ? WHERE issue_id = ?",
        (assigned_to_user_id, updated_by_user_id, issue_id)
    )


def set_issue_resolution(connection, issue_id, resolution_summary, resolution_details, updated_by_user_id):
    """
    Save resolution details and set status to AWAITING_CONFIRMATION.
    """
    connection.execute(
        """UPDATE support_issues
           SET resolution_summary = ?, resolution_details = ?, status = 'AWAITING_CONFIRMATION',
               resolution_provided_at = CURRENT_TIMESTAMP, awaiting_confirmation_at = CURRENT_TIMESTAMP,
               resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, updated_by = ?
           WHERE issue_id = ?""",
        (resolution_summary, resolution_details, updated_by_user_id, issue_id)
    )


def confirm_issue_resolution(connection, issue_id, user_id):
    """
    Mark issue resolution confirmed by reporter.
    """
    connection.execute(
        """UPDATE support_issues
           SET status = 'RESOLVED_CONFIRMED', resolved_confirmed_at = CURRENT_TIMESTAMP,
               resolution_confirmed_by_user_id = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?
           WHERE issue_id = ?""",
        (user_id, user_id, issue_id)
    )


def reopen_issue(connection, issue_id, user_id):
    """
    Set issue status to REOPENED and in_progress_at to CURRENT_TIMESTAMP.
    """
    connection.execute(
        """UPDATE support_issues
           SET status = 'REOPENED', reopened_at = CURRENT_TIMESTAMP, in_progress_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP, updated_by = ?
           WHERE issue_id = ?""",
        (user_id, issue_id)
    )


# ── ISSUE UPDATES / TIMELINE HISTORY ──

def add_issue_update(connection, issue_id, updated_by_user_id, update_type, message="", old_status=None, new_status=None, old_priority=None, new_priority=None, is_internal=0):
    """
    Add a comment/timeline entry for an issue.
    """
    cursor = connection.execute(
        """INSERT INTO support_issue_updates (
               issue_id, updated_by_user_id, update_type, message,
               old_status, new_status, old_priority, new_priority, is_internal
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (issue_id, updated_by_user_id, update_type, message, old_status, new_status, old_priority, new_priority, is_internal)
    )
    return cursor.lastrowid


def get_issue_updates(connection, issue_id, include_internal=True):
    """
    Fetch timeline/updates history for an issue.
    """
    sql = """
        SELECT u.*, user.full_name AS updated_by_name, user.role AS updated_by_role
        FROM support_issue_updates u
        LEFT JOIN users user ON user.id = u.updated_by_user_id
        WHERE u.issue_id = ?
    """
    if not include_internal:
        sql += " AND u.is_internal = 0"

    sql += " ORDER BY u.created_at ASC, u.update_id ASC"
    return connection.execute(sql, (issue_id,)).fetchall()


# ── ATTACHMENTS ──

def add_attachment(connection, attachment_data):
    """
    Insert attachment record.
    """
    cursor = connection.execute(
        """INSERT INTO support_issue_attachments (
               issue_id, update_id, uploaded_by_user_id, original_file_name,
               stored_file_name, file_path, file_url, mime_type, file_extension,
               file_size, storage_provider
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            attachment_data["issue_id"],
            attachment_data.get("update_id"),
            attachment_data["uploaded_by_user_id"],
            attachment_data["original_file_name"],
            attachment_data["stored_file_name"],
            attachment_data["file_path"],
            attachment_data["file_url"],
            attachment_data["mime_type"],
            attachment_data["file_extension"],
            attachment_data["file_size"],
            attachment_data.get("storage_provider", "LOCAL")
        )
    )
    return cursor.lastrowid


def get_issue_attachments(connection, issue_id):
    """
    Fetch attachments for an issue.
    """
    sql = """
        SELECT a.*, u.full_name AS uploader_name
        FROM support_issue_attachments a
        LEFT JOIN users u ON u.id = a.uploaded_by_user_id
        WHERE a.issue_id = ? AND a.status = 'Active'
        ORDER BY a.created_at ASC
    """
    return connection.execute(sql, (issue_id,)).fetchall()


def get_attachment_by_id(connection, attachment_id):
    """
    Fetch single attachment metadata by ID.
    """
    return connection.execute(
        "SELECT * FROM support_issue_attachments WHERE attachment_id = ? AND status = 'Active'",
        (attachment_id,)
    ).fetchone()


# ── ADMIN STATS & ANALYTICS ──

def get_support_dashboard_stats(connection):
    """
    Calculate summary stats for Admin dashboard.
    """
    total = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE is_archived = 0").fetchone()["cnt"]
    open_cnt = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status IN ('REPORTED', 'UNDER_REVIEW') AND is_archived = 0").fetchone()["cnt"]
    in_prog = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'IN_PROGRESS' AND is_archived = 0").fetchone()["cnt"]
    awaiting = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'AWAITING_CONFIRMATION' AND is_archived = 0").fetchone()["cnt"]
    resolved = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'RESOLVED_CONFIRMED' AND is_archived = 0").fetchone()["cnt"]
    reopened = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'REOPENED' AND is_archived = 0").fetchone()["cnt"]
    critical = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE priority = 'Critical' AND status NOT IN ('RESOLVED_CONFIRMED', 'CLOSED') AND is_archived = 0").fetchone()["cnt"]
    high = connection.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE priority = 'High' AND status NOT IN ('RESOLVED_CONFIRMED', 'CLOSED') AND is_archived = 0").fetchone()["cnt"]

    return {
        "total": total,
        "open": open_cnt,
        "in_progress": in_prog,
        "awaiting_confirmation": awaiting,
        "resolved": resolved,
        "reopened": reopened,
        "critical": critical,
        "high": high
    }

