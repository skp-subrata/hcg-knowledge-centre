"""Support & Helpdesk module: ported from the upstream author's standalone package (backend
business logic reused, controller/templates rewritten on this app's own security and design
conventions -- see support/controllers/support_bp.py's module docstring)."""
import json
import sqlite3

import pytest

import app as app_module
from support.services import issue_service


def _issue(db, issue_id):
    return db("SELECT * FROM support_issues WHERE issue_id = ?", (issue_id,))[0]


# ---------------------------------------------------------------------------
# Reporting and viewing an issue
# ---------------------------------------------------------------------------
def test_report_issue_creates_a_ticket_with_a_reporter_snapshot(student, world, db):
    response = student.post("/support/report", data={
        "title": "Certificate download fails", "description": "Clicking download does nothing on Safari.",
        "category_id": str(world.support_category_id),
    })
    assert response.status_code == 302
    rows = db("SELECT * FROM support_issues WHERE title = 'Certificate download fails'")
    assert len(rows) == 1
    issue = rows[0]
    assert issue["issue_number"].startswith("SUP-")
    assert issue["status"] == "REPORTED" and issue["priority"] == "Medium"
    assert issue["reporter_name"], "the reporter snapshot must be filled in from the users table"


def test_report_issue_rejects_a_short_title_or_description(student, world, db):
    before = db("SELECT COUNT(*) AS n FROM support_issues")[0]["n"]
    response = student.post("/support/report", data={"title": "Bad", "description": "too short", "category_id": str(world.support_category_id)})
    assert response.status_code == 302
    assert db("SELECT COUNT(*) AS n FROM support_issues")[0]["n"] == before


def test_only_the_reporter_or_admin_can_view_an_issue(student, moderator, admin, world):
    assert student.get(f"/support/issues/{world.support_issue_id}").status_code == 200  # student reported it
    assert admin.get(f"/support/issues/{world.support_issue_id}").status_code == 200
    response = moderator.get(f"/support/issues/{world.support_issue_id}")
    assert response.status_code == 302 and response.headers["Location"].endswith("/support")


def test_posting_a_message_requires_content_or_an_attachment(student, world, db):
    response = student.post(f"/support/issues/{world.support_issue_id}/message", data={"message": ""})
    assert response.status_code == 302
    assert db("SELECT COUNT(*) AS n FROM support_issue_updates WHERE issue_id = ?", (world.support_issue_id,))[0]["n"] == 0
    student.post(f"/support/issues/{world.support_issue_id}/message", data={"message": "Any update?"})
    assert db("SELECT COUNT(*) AS n FROM support_issue_updates WHERE issue_id = ? AND update_type = 'COMMENT'", (world.support_issue_id,))[0]["n"] == 1


def test_non_reporter_cannot_post_a_message(moderator, world, db):
    moderator.post(f"/support/issues/{world.support_issue_id}/message", data={"message": "not mine"})
    assert db("SELECT COUNT(*) AS n FROM support_issue_updates WHERE issue_id = ?", (world.support_issue_id,))[0]["n"] == 0


# ---------------------------------------------------------------------------
# Admin triage: status, priority, resolution -- and the state-machine guards
# ---------------------------------------------------------------------------
def test_only_admin_can_reach_the_admin_workspace(student, moderator, admin):
    assert student.get("/support/admin").status_code == 302
    assert moderator.get("/support/admin").status_code == 302
    assert admin.get("/support/admin").status_code == 200


def test_admin_can_change_status_along_an_allowed_transition(admin, world, db):
    admin.post(f"/support/admin/issues/{world.support_issue_id}/status", data={"status": "UNDER_REVIEW"})
    assert _issue(db, world.support_issue_id)["status"] == "UNDER_REVIEW"


def test_status_change_rejects_an_invalid_transition(admin, world, db):
    admin.post(f"/support/admin/issues/{world.support_issue_id}/status", data={"status": "RESOLVED_CONFIRMED"})
    assert _issue(db, world.support_issue_id)["status"] == "REPORTED"  # REPORTED -> RESOLVED_CONFIRMED is not allowed


def test_admin_can_provide_a_resolution_directly_from_reported(admin, world, db):
    response = admin.post(f"/support/admin/issues/{world.support_issue_id}/resolution", data={"summary": "Fixed it", "details": "Cleared the cache."})
    assert response.status_code == 302
    issue = _issue(db, world.support_issue_id)
    assert issue["status"] == "AWAITING_CONFIRMATION" and issue["resolution_summary"] == "Fixed it"


def test_resolution_cannot_be_resubmitted_once_awaiting_confirmation(db_path, world, db):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    with connection:
        issue_service.provide_resolution(connection, world.support_issue_id, "First fix", "Details", world.users["admin"])
        with pytest.raises(ValueError):
            issue_service.provide_resolution(connection, world.support_issue_id, "Second fix", "Details", world.users["admin"])
    connection.close()


def test_reporter_confirms_a_provided_resolution(db_path, student, world, db):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    with connection:
        issue_service.provide_resolution(connection, world.support_issue_id, "Fixed it", "Cleared the cache.", world.users["admin"])
    connection.close()

    response = student.post(f"/api/support/issues/{world.support_issue_id}/confirm-resolution", json={})
    assert response.status_code == 200 and response.get_json()["status"] == "RESOLVED_CONFIRMED"
    assert _issue(db, world.support_issue_id)["status"] == "RESOLVED_CONFIRMED"


def test_confirming_without_a_pending_resolution_is_rejected(student, world, db):
    response = student.post(f"/api/support/issues/{world.support_issue_id}/confirm-resolution", json={})
    assert response.status_code == 400
    assert _issue(db, world.support_issue_id)["status"] == "REPORTED"


def test_only_the_reporter_can_confirm_or_reopen(db_path, moderator, world, db):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    with connection:
        issue_service.provide_resolution(connection, world.support_issue_id, "Fixed it", "Details", world.users["admin"])
    connection.close()

    response = moderator.post(f"/api/support/issues/{world.support_issue_id}/confirm-resolution", json={})
    assert response.status_code == 400
    assert _issue(db, world.support_issue_id)["status"] == "AWAITING_CONFIRMATION"  # unchanged


def test_reporter_can_reopen_a_confirmed_issue(db_path, student, world, db):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    with connection:
        issue_service.provide_resolution(connection, world.support_issue_id, "Fixed it", "Details", world.users["admin"])
        issue_service.confirm_resolution(connection, world.support_issue_id, world.users["student"])
    connection.close()

    response = student.post(f"/api/support/issues/{world.support_issue_id}/reopen", json={"reason": "Broke again"})
    assert response.status_code == 200 and response.get_json()["status"] == "REOPENED"


def test_reopen_is_rejected_when_nothing_is_awaiting_confirmation(student, world, db):
    response = student.post(f"/api/support/issues/{world.support_issue_id}/reopen", json={})
    assert response.status_code == 400
    assert _issue(db, world.support_issue_id)["status"] == "REPORTED"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
def test_only_admin_can_create_a_category(student, admin, db):
    student.get("/support")  # triggers the blueprint's lazy table creation on this fresh db copy
    before = db("SELECT COUNT(*) AS n FROM support_categories")[0]["n"]
    response = student.post("/api/support/categories", json={"name": "Billing", "code": "BILL"})
    assert response.status_code == 403
    assert db("SELECT COUNT(*) AS n FROM support_categories")[0]["n"] == before

    response = admin.post("/api/support/categories", json={"name": "Billing", "code": "BILL"})
    assert response.status_code == 201
    assert db("SELECT COUNT(*) AS n FROM support_categories WHERE code = 'BILL'")[0]["n"] == 1


# ---------------------------------------------------------------------------
# Attachments: ownership and path traversal
# ---------------------------------------------------------------------------
def test_attachment_download_is_forbidden_to_a_non_owner(moderator, world):
    response = moderator.get(f"/api/support/attachments/file/{world.support_issue_id}/anything.pdf")
    assert response.status_code == 403


def test_attachment_path_traversal_is_blocked(student, world):
    response = student.get(f"/api/support/attachments/file/{world.support_issue_id}/..%2F..%2Fapp.py")
    assert response.status_code in (404, 400)
    assert b"import sqlite3" not in response.data  # app.py's own first line must never be served


# ---------------------------------------------------------------------------
# CSRF: every mutating form/fetch in the redesigned templates must carry a token
# ---------------------------------------------------------------------------
def test_every_post_form_in_support_templates_carries_a_csrf_token():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "support" / "templates" / "support"
    for template in root.glob("*.html"):
        html = template.read_text(encoding="utf-8")
        forms = re.findall(r'<form\b[^>]*\bmethod="post"[^>]*>', html, flags=re.I)
        tokens = html.count('name="csrf_token"')
        assert tokens == len(forms), f"{template.name}: {len(forms)} POST forms but {tokens} csrf_token inputs"


def test_form_post_without_a_csrf_token_is_rejected(admin, world, db, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "CSRF_ENABLED", True)
    before = _issue(db, world.support_issue_id)["priority"]
    admin.post(f"/support/admin/issues/{world.support_issue_id}/priority", data={"priority": "Critical"})
    assert _issue(db, world.support_issue_id)["priority"] == before  # rejected before it ever reached the route


# ---------------------------------------------------------------------------
# The support_* schema is isolated from the primary application tables
# ---------------------------------------------------------------------------
def test_support_tables_exist_and_seed_categories(student, db):
    student.get("/support")  # triggers the blueprint's lazy table creation on this fresh db copy
    tables = {r["name"] for r in db("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"support_categories", "support_issues", "support_issue_updates", "support_issue_attachments", "support_audit_logs"} <= tables
    assert db("SELECT COUNT(*) AS n FROM support_categories")[0]["n"] >= 14
