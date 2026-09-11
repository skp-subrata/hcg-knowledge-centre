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


def test_additional_widget_categories_are_seeded_and_survive_reseeding(db_path):
    """Regression test for the ordering fix: these categories are seeded unconditionally inside
    init_support_db() itself (never via a numbered init_scripts/*.sql migration), because
    support_categories doesn't exist yet at the point apply_init_scripts() runs on a fresh
    database. Calling init_support_db() again (as happens on every app restart) must not
    duplicate rows -- UNIQUE(code) + INSERT OR IGNORE make it a no-op."""
    from support.models.schema import init_support_db

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    with connection:
        init_support_db(connection)
        init_support_db(connection)
    codes = {r["code"] for r in connection.execute("SELECT code FROM support_categories").fetchall()}
    assert {"BUG_REPORT", "FEATURE_REQUEST", "GENERAL_FEEDBACK"} <= codes
    dupes = connection.execute("SELECT code FROM support_categories GROUP BY code HAVING COUNT(*) > 1").fetchall()
    assert dupes == []
    connection.close()


# ---------------------------------------------------------------------------
# Feedback widget -> quick support ticket (+ best-effort GitHub mirror)
# ---------------------------------------------------------------------------
def test_quick_feedback_creates_a_real_ticket_with_identity_and_context(student, world, db):
    response = student.post("/api/support/quick-feedback", json={
        "type": "bug",
        "title": "Certificate download fails",
        "details": "Clicking download does nothing on Safari.",
        "context": {"url": "/course/1", "viewport": "1024x768", "user_agent": "Mozilla/5.0", "platform": "MacIntel"},
        "logs": [{"level": "error", "message": "boom", "time": "2026-01-01T00:00:00.000Z"}],
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["issue_number"].startswith("SUP-")

    issue = db("SELECT * FROM support_issues WHERE title = 'Certificate download fails'")[0]
    assert data["issue_url"].endswith(f"/support/issues/{issue['issue_id']}")
    assert issue["module_name"] == "Feedback Widget"
    assert issue["page_url"] == "/course/1" and issue["device_info"] == "1024x768"
    assert issue["browser_info"] == "Mozilla/5.0" and issue["os_info"] == "MacIntel"
    assert issue["reporter_name"], "identity is always captured server-side, same as /support/report"
    assert "boom" in issue["description"]  # included console log

    category = db("SELECT code FROM support_categories WHERE id = ?", (issue["category_id"],))[0]
    assert category["code"] == "BUG_REPORT"


@pytest.mark.parametrize("feedback_type,expected_code", [
    ("bug", "BUG_REPORT"), ("enhancement", "FEATURE_REQUEST"), ("question", "GENERAL_FEEDBACK"), ("nonsense", "GENERAL_FEEDBACK"),
])
def test_quick_feedback_maps_widget_type_to_the_right_category(student, db, feedback_type, expected_code):
    response = student.post("/api/support/quick-feedback", json={"type": feedback_type, "title": f"Type {feedback_type}", "details": "details"})
    assert response.status_code == 200
    issue = db("SELECT category_id FROM support_issues WHERE title = ?", (f"Type {feedback_type}",))[0]
    category = db("SELECT code FROM support_categories WHERE id = ?", (issue["category_id"],))[0]
    assert category["code"] == expected_code


def test_quick_feedback_requires_a_title_and_details(student, db):
    before = db("SELECT COUNT(*) AS n FROM support_issues")[0]["n"]
    response = student.post("/api/support/quick-feedback", json={"type": "bug", "title": "", "details": ""})
    assert response.status_code == 400
    assert db("SELECT COUNT(*) AS n FROM support_issues")[0]["n"] == before


def test_quick_feedback_requires_login(anon):
    response = anon.post("/api/support/quick-feedback", json={"type": "bug", "title": "x", "details": "y"})
    assert response.status_code == 401


def test_creating_a_ticket_notifies_every_admin(student, world, db):
    """create_new_issue() previously notified no one on creation -- only update_status()/
    provide_resolution() did. This covers the fix at its root, so it also protects the existing
    /support/report form, not just the new widget endpoint."""
    admin_id = world.users["admin"]
    before = db("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND type = 'SUPPORT_ISSUE_CREATED'", (admin_id,))[0]["n"]
    student.post("/api/support/quick-feedback", json={"type": "bug", "title": "Please notify admins", "details": "details"})
    after = db("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND type = 'SUPPORT_ISSUE_CREATED'", (admin_id,))[0]["n"]
    assert after == before + 1


def test_github_mirror_is_a_no_op_without_a_token(student, monkeypatch, db):
    monkeypatch.delenv("GITHUB_FEEDBACK_TOKEN", raising=False)
    response = student.post("/api/support/quick-feedback", json={"type": "bug", "title": "No token set", "details": "details"})
    assert response.status_code == 200 and response.get_json()["success"] is True
    issue_id = db("SELECT issue_id FROM support_issues WHERE title = 'No token set'")[0]["issue_id"]
    mirrored = db("SELECT COUNT(*) AS n FROM support_issue_updates WHERE issue_id = ? AND message LIKE 'Mirrored to GitHub:%'", (issue_id,))[0]["n"]
    assert mirrored == 0


def test_github_mirror_failure_never_blocks_ticket_creation(student, monkeypatch, db):
    """The whole point of 'best-effort': a broken/unreachable GitHub call must never affect the
    ticket that's already been committed, nor the response returned to the widget."""
    # NOT `import support.controllers.support_bp as x` -- support/controllers/__init__.py does
    # `from .support_bp import support_bp`, which shadows the package's `support_bp` *attribute*
    # with the Blueprint object, and `import a.b.c as x` resolves via that attribute chain.
    # importlib sidesteps it by reading straight out of sys.modules.
    import importlib
    support_bp_module = importlib.import_module("support.controllers.support_bp")

    def _boom(*args, **kwargs):
        raise RuntimeError("network is down")

    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "fake-token")
    monkeypatch.setattr(support_bp_module.requests, "post", _boom)

    response = student.post("/api/support/quick-feedback", json={"type": "bug", "title": "Mirror explodes", "details": "details"})
    assert response.status_code == 200 and response.get_json()["success"] is True
    assert db("SELECT COUNT(*) AS n FROM support_issues WHERE title = 'Mirror explodes'")[0]["n"] == 1


def test_github_mirror_success_is_recorded_on_the_ticket_timeline(student, monkeypatch, db):
    import importlib
    support_bp_module = importlib.import_module("support.controllers.support_bp")

    class _FakeResponse:
        status_code = 201
        def json(self):
            return {"html_url": "https://github.com/skp-subrata/hcg-knowledge-centre/issues/999"}

    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "fake-token")
    monkeypatch.setattr(support_bp_module.requests, "post", lambda *a, **k: _FakeResponse())

    response = student.post("/api/support/quick-feedback", json={"type": "bug", "title": "Mirror succeeds", "details": "details"})
    assert response.status_code == 200
    issue_id = db("SELECT issue_id FROM support_issues WHERE title = 'Mirror succeeds'")[0]["issue_id"]
    updates = db("SELECT message FROM support_issue_updates WHERE issue_id = ? AND update_type = 'SYSTEM' AND message LIKE 'Mirrored to GitHub:%'", (issue_id,))
    assert len(updates) == 1
    assert "issues/999" in updates[0]["message"]
