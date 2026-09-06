"""
Issue Service.
Core business logic engine for issue creation, lifecycle state transitions,
resolution flows, confirmation, and reopening.
"""

from support.repositories import issue_repository, category_repository, audit_repository
from support.services import tat_service, notification_publisher, attachment_service


# Valid issue status lifecycle transitions map
ALLOWED_STATUS_TRANSITIONS = {
    "REPORTED": {"UNDER_REVIEW", "IN_PROGRESS", "CLOSED"},
    "UNDER_REVIEW": {"IN_PROGRESS", "CLOSED"},
    "IN_PROGRESS": {"RESOLUTION_PROVIDED", "CLOSED"},
    "RESOLUTION_PROVIDED": {"AWAITING_CONFIRMATION", "IN_PROGRESS", "CLOSED"},
    "AWAITING_CONFIRMATION": {"RESOLVED_CONFIRMED", "REOPENED", "CLOSED"},
    "RESOLVED_CONFIRMED": {"CLOSED", "REOPENED"},
    "REOPENED": {"IN_PROGRESS", "UNDER_REVIEW", "CLOSED"},
    "CLOSED": {"REOPENED"}
}

ALLOWED_PRIORITIES = {"Critical", "High", "Medium", "Low"}


def create_new_issue(connection, user_id, title, description, category_id, priority="Medium", module_name="", page_url="", device_info="", browser_info="", os_info="", attachments=None):
    """
    Create a new issue with auto-generated issue number, reporter snapshot, timeline entry,
    and process any file attachments.
    """
    # 1. Fetch reporter snapshot from users table
    user = connection.execute(
        "SELECT full_name, employee_id, email, phone_number FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        raise ValueError("User not found.")

    reporter_name = user["full_name"] or "Unknown User"
    reporter_emp_id = user["employee_id"] or ""
    reporter_email = user["email"] or ""
    reporter_phone = user["phone_number"] or ""

    # 2. Generate issue number
    issue_number = issue_repository.generate_next_issue_number(connection)

    issue_data = {
        "issue_number": issue_number,
        "reported_by_user_id": user_id,
        "reporter_name": reporter_name,
        "reporter_employee_id": reporter_emp_id,
        "reporter_email": reporter_email,
        "reporter_phone": reporter_phone,
        "title": title.strip(),
        "description": description.strip(),
        "category_id": category_id,
        "priority": priority if priority in ALLOWED_PRIORITIES else "Medium",
        "module_name": module_name.strip(),
        "page_url": page_url.strip(),
        "device_info": device_info.strip(),
        "browser_info": browser_info.strip(),
        "os_info": os_info.strip(),
        "source_application": "LMS"
    }

    issue_id = issue_repository.create_issue(connection, issue_data)

    # 3. Create initial timeline entry
    update_id = issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="SYSTEM",
        message="Issue reported by user.",
        new_status="REPORTED"
    )

    # 4. Process file attachments if provided
    saved_attachments = []
    if attachments:
        for file_obj in attachments:
            if file_obj and getattr(file_obj, "filename", None):
                att = attachment_service.save_attachment(connection, issue_id, file_obj, user_id, update_id=update_id)
                saved_attachments.append(att)

    # 5. Log audit
    audit_repository.log_audit(connection, user_id, "CREATE_ISSUE", issue_id=issue_id, new_value=issue_number)

    return issue_repository.get_issue_by_id(connection, issue_id)


def update_status(connection, issue_id, new_status, user_id, is_admin=False, message=""):
    """
    Validate and update issue status based on allowed lifecycle transitions.
    """
    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    current_status = issue["status"]
    if current_status == new_status:
        return issue

    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(f"Invalid status transition from {current_status} to {new_status}.")

    timestamp_field = None
    if new_status == "UNDER_REVIEW" and not issue["under_review_at"]:
        timestamp_field = "under_review_at"
    elif new_status == "IN_PROGRESS" and not issue["in_progress_at"]:
        timestamp_field = "in_progress_at"
    elif new_status == "CLOSED" and not issue["closed_at"]:
        timestamp_field = "closed_at"

    # Set first response timestamp on initial admin action if missing
    if is_admin and not issue["first_response_at"]:
        connection.execute(
            "UPDATE support_issues SET first_response_at = CURRENT_TIMESTAMP WHERE issue_id = ?",
            (issue_id,)
        )

    issue_repository.update_issue_status(connection, issue_id, new_status, user_id, timestamp_field=timestamp_field)

    # Record update entry
    msg = message.strip() or f"Status changed from {current_status} to {new_status}."
    issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="STATUS_CHANGE",
        message=msg,
        old_status=current_status,
        new_status=new_status
    )

    audit_repository.log_audit(connection, user_id, "STATUS_CHANGE", issue_id=issue_id, old_value=current_status, new_value=new_status)

    # Publish notification to reporter
    notification_publisher.publish_support_event(
        connection, "UPDATED", issue["reported_by_user_id"],
        f"Your support issue #{issue['issue_number']} status was updated to {new_status}.",
        target_url=f"/support/issues/{issue_id}"
    )

    return issue_repository.get_issue_by_id(connection, issue_id)


def update_priority(connection, issue_id, new_priority, user_id):
    """
    Update priority of an issue (Admin only).
    """
    if new_priority not in ALLOWED_PRIORITIES:
        raise ValueError(f"Invalid priority '{new_priority}'. Must be one of {ALLOWED_PRIORITIES}.")

    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    old_priority = issue["priority"]
    if old_priority == new_priority:
        return issue

    issue_repository.update_issue_priority(connection, issue_id, new_priority, user_id)

    issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="PRIORITY_CHANGE",
        message=f"Priority changed from {old_priority} to {new_priority}.",
        old_priority=old_priority,
        new_priority=new_priority
    )

    audit_repository.log_audit(connection, user_id, "PRIORITY_CHANGE", issue_id=issue_id, old_value=old_priority, new_value=new_priority)

    return issue_repository.get_issue_by_id(connection, issue_id)


def provide_resolution(connection, issue_id, summary, details, user_id, attachments=None):
    """
    Save resolution summary & details provided by Admin/support,
    transition status to AWAITING_CONFIRMATION, and notify user.
    """
    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    old_status = issue["status"]
    if old_status in ("AWAITING_CONFIRMATION", "RESOLVED_CONFIRMED", "CLOSED"):
        raise ValueError(f"A resolution cannot be submitted while the issue is {old_status}.")
    issue_repository.set_issue_resolution(connection, issue_id, summary.strip(), details.strip(), user_id)

    update_id = issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="RESOLUTION",
        message=f"Resolution Provided: {summary.strip()}\n\n{details.strip()}",
        old_status=old_status,
        new_status="AWAITING_CONFIRMATION"
    )

    # Save resolution attachments if any
    if attachments:
        for file_obj in attachments:
            if file_obj and getattr(file_obj, "filename", None):
                attachment_service.save_attachment(connection, issue_id, file_obj, user_id, update_id=update_id)

    audit_repository.log_audit(connection, user_id, "RESOLUTION_PROVIDED", issue_id=issue_id, old_value=old_status, new_value="AWAITING_CONFIRMATION")

    notification_publisher.publish_support_event(
        connection, "RESOLUTION_PROVIDED", issue["reported_by_user_id"],
        f"Resolution provided for your support issue #{issue['issue_number']}. Please verify.",
        target_url=f"/support/issues/{issue_id}"
    )

    return issue_repository.get_issue_by_id(connection, issue_id)


def confirm_resolution(connection, issue_id, user_id, comment=""):
    """
    Reporter confirms resolution -> status becomes RESOLVED_CONFIRMED.
    """
    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    if issue["reported_by_user_id"] != user_id:
        raise ValueError("Only the issue reporter can confirm resolution.")

    old_status = issue["status"]
    if "RESOLVED_CONFIRMED" not in ALLOWED_STATUS_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"There is no resolution awaiting confirmation (issue is {old_status}).")
    issue_repository.confirm_issue_resolution(connection, issue_id, user_id)

    msg = "Resolution confirmed by reporter."
    if comment.strip():
        msg += f" Feedback: {comment.strip()}"

    issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="USER_CONFIRMATION",
        message=msg,
        old_status=old_status,
        new_status="RESOLVED_CONFIRMED"
    )

    audit_repository.log_audit(connection, user_id, "USER_CONFIRMATION", issue_id=issue_id, old_value=old_status, new_value="RESOLVED_CONFIRMED")

    return issue_repository.get_issue_by_id(connection, issue_id)


def reopen_issue_flow(connection, issue_id, user_id, reason=""):
    """
    Reporter rejects resolution / reopens issue -> status becomes REOPENED.
    """
    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    if issue["reported_by_user_id"] != user_id:
        raise ValueError("Only the issue reporter can reopen this issue.")

    old_status = issue["status"]
    if "REOPENED" not in ALLOWED_STATUS_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"This issue cannot be reopened while it is {old_status}.")
    issue_repository.reopen_issue(connection, issue_id, user_id)

    msg = "Issue reopened by reporter."
    if reason.strip():
        msg += f" Reason: {reason.strip()}"

    issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="REOPENED",
        message=msg,
        old_status=old_status,
        new_status="REOPENED"
    )

    audit_repository.log_audit(connection, user_id, "REOPEN_ISSUE", issue_id=issue_id, old_value=old_status, new_value="REOPENED")

    return issue_repository.get_issue_by_id(connection, issue_id)


def add_comment(connection, issue_id, user_id, message, is_internal=0, attachments=None):
    """
    Add a comment/message to an issue conversation.
    """
    issue = issue_repository.get_issue_by_id(connection, issue_id)
    if not issue:
        raise ValueError("Issue not found.")

    update_id = issue_repository.add_issue_update(
        connection,
        issue_id=issue_id,
        updated_by_user_id=user_id,
        update_type="COMMENT",
        message=message.strip(),
        is_internal=is_internal
    )

    if attachments:
        for file_obj in attachments:
            if file_obj and getattr(file_obj, "filename", None):
                attachment_service.save_attachment(connection, issue_id, file_obj, user_id, update_id=update_id)

    # Touch issue updated_at timestamp
    connection.execute("UPDATE support_issues SET updated_at = CURRENT_TIMESTAMP WHERE issue_id = ?", (issue_id,))

    return update_id

