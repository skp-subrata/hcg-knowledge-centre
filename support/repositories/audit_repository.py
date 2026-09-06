"""
Audit Repository.
Logs administrative and sensitive actions in support_audit_logs.
"""


def log_audit(connection, performed_by_user_id, action, issue_id=None, old_value=None, new_value=None, ip_address="", user_agent=""):
    """
    Insert an audit trail entry.
    """
    connection.execute(
        """INSERT INTO support_audit_logs
           (issue_id, performed_by_user_id, action, old_value, new_value, ip_address, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (issue_id, performed_by_user_id, action, old_value, new_value, ip_address, user_agent)
    )


def get_audit_logs_for_issue(connection, issue_id):
    """
    Fetch audit logs associated with a specific issue.
    """
    return connection.execute(
        """SELECT a.*, u.full_name as performed_by_name
           FROM support_audit_logs a
           LEFT JOIN users u ON u.id = a.performed_by_user_id
           WHERE a.issue_id = ?
           ORDER BY a.created_at ASC""",
        (issue_id,)
    ).fetchall()

