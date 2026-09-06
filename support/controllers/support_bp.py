"""
Support Module Flask Blueprint (Controllers & Routes).
Mounts all frontend templates and RESTful API routes under /support and /api/support.

Ported from the upstream author's standalone module (originally raw Tailwind-CDN templates
with no CSRF tokens at all, which the app-wide CSRF check would reject outright): the
business-logic layers (models/repositories/services/validators) are unchanged, the routes
below use this app's own login/admin conventions instead of the module's original ones
(effective `role`, not `actual_role`, and blocked while impersonating -- matching every other
admin-only area of the app), and the five templates are rewritten on the shared design system
with CSRF tokens on every form and fetch call.
"""

from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, send_file
)


def get_db():
    from app import get_db as _get_db
    return _get_db()


def _log_activity(connection, user_id, event_type, details=None):
    """Best-effort link into the admin System & activity log (see app.py's log_activity());
    never lets a logging failure break a support-module request."""
    try:
        from app import log_activity as _log
        _log(connection, user_id, event_type, details)
    except Exception:
        pass

from support.config import SUPPORT_UPLOAD_DIR
from support.repositories import issue_repository, category_repository
from support.services import issue_service, tat_service
from support.validators import validate_create_issue_payload


support_bp = Blueprint(
    "support",
    __name__,
    template_folder="../templates",
    url_prefix=""
)


# ── AUTHENTICATION DECORATORS ──
# Deliberately match app.py's own login_required/admin_required semantics: the *effective*
# role (session['role']), not actual_role, and blocked while impersonating -- so switching to
# "Student view" (or admin's view-as) actually restricts the support admin workspace, the same
# way it restricts every other admin-only page in this app.

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "message": "Authentication required."}), 401
            flash("Please sign in to access the Support & Helpdesk workspace.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "message": "Authentication required."}), 401
            flash("Please sign in to continue.", "error")
            return redirect(url_for("home"))
        if session.get("role") != "admin" or session.get("impersonator_id"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "message": "Administrator access required."}), 403
            flash("Only administrators can access the support admin workspace.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def _is_admin():
    return session.get("role") == "admin" and not session.get("impersonator_id")


# ── FRONTEND UI ROUTES ──

@support_bp.route("/support", methods=["GET"])
@login_required
def user_dashboard():
    """User Support Dashboard - shows the signed-in user's reported issues."""
    user_id = session["user_id"]
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    category_id_val = int(category_id) if category_id.isdigit() else None

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
        issues_page = issue_repository.get_user_issues(
            conn, user_id=user_id, page=page, page_size=15,
            search=search, category_id=category_id_val,
            status_filter=status_filter, priority_filter=priority_filter
        )
        stats = {
            "total": conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND is_archived = 0", (user_id,)).fetchone()["cnt"],
            "in_progress": conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'IN_PROGRESS' AND is_archived = 0", (user_id,)).fetchone()["cnt"],
            "awaiting_confirmation": conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'AWAITING_CONFIRMATION' AND is_archived = 0", (user_id,)).fetchone()["cnt"],
            "resolved": conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'RESOLVED_CONFIRMED' AND is_archived = 0", (user_id,)).fetchone()["cnt"],
        }

    return render_template(
        "support/user_dashboard.html",
        issues_page=issues_page, categories=categories, stats=stats,
        current_search=search, current_category=category_id, current_status=status_filter, current_priority=priority_filter,
        user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"),
        profile_picture=session.get("profile_picture"),
    )


@support_bp.route("/support/report", methods=["GET", "POST"])
@login_required
def report_issue():
    """Report an issue: form + submission."""
    user_id = session["user_id"]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category_id = request.form.get("category_id", type=int)
        attachments = request.files.getlist("attachments")

        is_valid, errors = validate_create_issue_payload(title, description, category_id)
        if not is_valid:
            for err in errors:
                flash(err, "error")
            return redirect(url_for("support.report_issue"))

        try:
            with get_db() as conn:
                issue = issue_service.create_new_issue(
                    conn, user_id=user_id, title=title, description=description, category_id=category_id,
                    module_name=request.form.get("module_name", "").strip(),
                    page_url=request.form.get("page_url", "").strip(),
                    device_info=request.form.get("device_info", "").strip(),
                    browser_info=request.form.get("browser_info", "").strip(),
                    os_info=request.form.get("os_info", "").strip(),
                    attachments=attachments,
                )
                _log_activity(conn, user_id, "support_issue_created", {"issue_id": issue["issue_id"], "issue_number": issue["issue_number"]})
            flash(f"Support ticket #{issue['issue_number']} created successfully!", "success")
            return redirect(url_for("support.issue_detail", issue_id=issue["issue_id"]))
        except ValueError as ve:
            flash(str(ve), "error")
            return redirect(url_for("support.report_issue"))

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
        u_row = conn.execute("SELECT full_name, employee_id, email, phone_number FROM users WHERE id = ?", (user_id,)).fetchone()

    user_snapshot = {
        "name": u_row["full_name"] if u_row else session.get("user", ""),
        "employee_id": u_row["employee_id"] if u_row else "",
        "email": u_row["email"] if u_row else "",
        "phone": u_row["phone_number"] if u_row else "",
    }
    return render_template(
        "support/create_issue.html", categories=categories, user_snapshot=user_snapshot,
        user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"),
        profile_picture=session.get("profile_picture"),
    )


@support_bp.route("/support/issues/<int:issue_id>", methods=["GET"])
@login_required
def issue_detail(issue_id):
    """Issue detail and conversation timeline."""
    user_id = session["user_id"]
    is_admin = _is_admin()

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            flash("Support issue not found.", "error")
            return redirect(url_for("support.user_dashboard"))
        if not is_admin and issue["reported_by_user_id"] != user_id:
            flash("You are not authorized to view this support issue.", "error")
            return redirect(url_for("support.user_dashboard"))

        updates = [dict(u) for u in issue_repository.get_issue_updates(conn, issue_id, include_internal=is_admin)]
        attachments = [dict(a) for a in issue_repository.get_issue_attachments(conn, issue_id)]
        tat = tat_service.calculate_issue_tat(issue)

    next_statuses = [{"id": s, "name": s.replace("_", " ").title()} for s in sorted(issue_service.ALLOWED_STATUS_TRANSITIONS.get(issue["status"], set()))]

    return render_template(
        "support/issue_detail.html", issue=dict(issue), updates=updates, attachments=attachments, tat=tat, next_statuses=next_statuses,
        is_admin=is_admin, current_user_id=user_id,
        user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"),
        profile_picture=session.get("profile_picture"),
    )


@support_bp.route("/support/issues/<int:issue_id>/message", methods=["POST"])
@login_required
def post_issue_message(issue_id):
    """Post a message/comment to an issue's conversation."""
    user_id = session["user_id"]
    is_admin = _is_admin()
    message = request.form.get("message", "").strip()
    attachments = request.files.getlist("attachments")

    if not message and not any(f.filename for f in attachments if f):
        flash("Message content or a file attachment is required.", "error")
        return redirect(url_for("support.issue_detail", issue_id=issue_id))

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            flash("Issue not found.", "error")
            return redirect(url_for("support.user_dashboard"))
        if not is_admin and issue["reported_by_user_id"] != user_id:
            flash("You are not authorized to update this issue.", "error")
            return redirect(url_for("support.user_dashboard"))
        issue_service.add_comment(conn, issue_id, user_id, message, is_internal=0, attachments=attachments)

    flash("Message posted to the timeline.", "success")
    return redirect(url_for("support.issue_detail", issue_id=issue_id))


# ── ADMIN FRONTEND ROUTES ──

@support_bp.route("/support/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    """Admin support panel: triage queue with search and filters."""
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    category_id_val = int(category_id) if category_id.isdigit() else None

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn, active_only=False)]
        stats = issue_repository.get_support_dashboard_stats(conn)
        issues_page = issue_repository.get_admin_issues(
            conn, page=page, page_size=15, search=search,
            category_id=category_id_val, status_filter=status_filter, priority_filter=priority_filter,
        )

    return render_template(
        "support/admin_dashboard.html", issues_page=issues_page, categories=categories, stats=stats,
        current_search=search, current_category=category_id, current_status=status_filter, current_priority=priority_filter,
        user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"),
        profile_picture=session.get("profile_picture"),
    )


@support_bp.route("/support/admin/issues/<int:issue_id>/status", methods=["POST"])
@admin_required
def admin_update_status(issue_id):
    new_status = request.form.get("status", "").strip()
    user_id = session["user_id"]
    try:
        with get_db() as conn:
            issue_service.update_status(conn, issue_id, new_status, user_id, is_admin=True)
            if new_status in ("RESOLUTION_PROVIDED", "RESOLVED_CONFIRMED", "CLOSED"):
                _log_activity(conn, user_id, "support_issue_status_changed", {"issue_id": issue_id, "status": new_status})
        flash(f"Issue status updated to {new_status.replace('_', ' ').title()}.", "success")
    except ValueError as e:
        flash(f"Could not update status: {e}", "error")
    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/issues/<int:issue_id>/priority", methods=["POST"])
@admin_required
def admin_update_priority(issue_id):
    new_priority = request.form.get("priority", "").strip()
    user_id = session["user_id"]
    try:
        with get_db() as conn:
            issue_service.update_priority(conn, issue_id, new_priority, user_id)
        flash(f"Issue priority updated to {new_priority}.", "success")
    except ValueError as e:
        flash(f"Could not update priority: {e}", "error")
    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/issues/<int:issue_id>/resolution", methods=["POST"])
@admin_required
def admin_provide_resolution(issue_id):
    summary = request.form.get("summary", "").strip()
    details = request.form.get("details", "").strip()
    attachments = request.files.getlist("attachments")
    user_id = session["user_id"]

    if not summary or not details:
        flash("Resolution summary and details are both required.", "error")
        return redirect(url_for("support.issue_detail", issue_id=issue_id))

    try:
        with get_db() as conn:
            issue_service.provide_resolution(conn, issue_id, summary, details, user_id, attachments=attachments)
            _log_activity(conn, user_id, "support_issue_status_changed", {"issue_id": issue_id, "status": "RESOLUTION_PROVIDED"})
        flash("Resolution submitted to the reporter for confirmation.", "success")
    except ValueError as e:
        flash(f"Could not submit resolution: {e}", "error")
    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/reports", methods=["GET"])
@admin_required
def admin_reports():
    """SLA / TAT analytics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE is_archived = 0").fetchone()["cnt"]
        resolved_cnt = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'RESOLVED_CONFIRMED' AND is_archived = 0").fetchone()["cnt"]

        rows = conn.execute("SELECT * FROM support_issues WHERE is_archived = 0").fetchall()
        first_resp_secs, resolution_secs, confirmation_secs = [], [], []
        for r in rows:
            tat = tat_service.calculate_issue_tat(r)
            if tat["first_response_seconds"]:
                first_resp_secs.append(tat["first_response_seconds"])
            if tat["resolution_seconds"]:
                resolution_secs.append(tat["resolution_seconds"])
            if tat["confirmation_seconds"]:
                confirmation_secs.append(tat["confirmation_seconds"])

        cat_rows = conn.execute("""
            SELECT c.name, COUNT(i.issue_id) AS cnt FROM support_categories c
            LEFT JOIN support_issues i ON i.category_id = c.id AND i.is_archived = 0
            GROUP BY c.id ORDER BY cnt DESC
        """).fetchall()
        cat_breakdown = [{"name": cr["name"], "count": cr["cnt"], "percentage": round((cr["cnt"] / total * 100), 1) if total else 0} for cr in cat_rows]

        prio_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for pr in conn.execute("SELECT priority, COUNT(*) AS cnt FROM support_issues WHERE is_archived = 0 GROUP BY priority").fetchall():
            if pr["priority"] in prio_counts:
                prio_counts[pr["priority"]] = pr["cnt"]

    report = {
        "total_issues": total,
        "resolved_issues": resolved_cnt,
        "resolution_rate": round((resolved_cnt / total * 100), 1) if total else 0,
        "avg_first_response_tat": tat_service.format_duration(sum(first_resp_secs) / len(first_resp_secs) if first_resp_secs else None),
        "avg_resolution_tat": tat_service.format_duration(sum(resolution_secs) / len(resolution_secs) if resolution_secs else None),
        "avg_confirmation_tat": tat_service.format_duration(sum(confirmation_secs) / len(confirmation_secs) if confirmation_secs else None),
        "category_breakdown": cat_breakdown,
        "priority_breakdown": prio_counts,
    }
    return render_template(
        "support/admin_reports.html", report=report,
        user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"),
        profile_picture=session.get("profile_picture"),
    )


# ── SECURE ATTACHMENT ACCESS ──

@support_bp.route("/api/support/attachments/file/<int:issue_id>/<filename>", methods=["GET"])
@login_required
def serve_attachment_file(issue_id, filename):
    """Stream an attachment after verifying the caller owns the issue or is an admin."""
    user_id = session["user_id"]
    is_admin = _is_admin()

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            return jsonify({"success": False, "message": "Issue not found."}), 404
        if not is_admin and issue["reported_by_user_id"] != user_id:
            return jsonify({"success": False, "message": "Forbidden."}), 403

    file_path = (SUPPORT_UPLOAD_DIR / str(issue_id) / filename).resolve()
    if SUPPORT_UPLOAD_DIR.resolve() not in file_path.parents or not file_path.is_file():
        return jsonify({"success": False, "message": "Attachment not found."}), 404
    return send_file(file_path, download_name=filename)


# ── JSON APIS (used by the redesigned templates' fetch calls) ──

@support_bp.route("/api/support/issues/<int:issue_id>/confirm-resolution", methods=["POST"])
@login_required
def api_confirm_resolution(issue_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        with get_db() as conn:
            issue = issue_service.confirm_resolution(conn, issue_id, user_id, comment=data.get("comment", "").strip())
            _log_activity(conn, user_id, "support_issue_status_changed", {"issue_id": issue_id, "status": issue["status"]})
        return jsonify({"success": True, "message": "Resolution confirmed.", "status": issue["status"]})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400


@support_bp.route("/api/support/issues/<int:issue_id>/reopen", methods=["POST"])
@login_required
def api_reopen_issue(issue_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        with get_db() as conn:
            issue = issue_service.reopen_issue_flow(conn, issue_id, user_id, reason=data.get("reason", "").strip())
            _log_activity(conn, user_id, "support_issue_status_changed", {"issue_id": issue_id, "status": issue["status"]})
        return jsonify({"success": True, "message": "Issue reopened.", "status": issue["status"]})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400


@support_bp.route("/api/support/categories", methods=["GET", "POST"])
@login_required
def api_categories():
    if request.method == "POST":
        if not _is_admin():
            return jsonify({"success": False, "message": "Administrator access required."}), 403
        data = request.get_json(silent=True) or request.form
        name = data.get("name", "").strip()
        code = data.get("code", "").strip()
        if not name or not code:
            return jsonify({"success": False, "message": "Category name and code are both required."}), 400
        with get_db() as conn:
            category_id = category_repository.create_category(conn, name, code, data.get("description", "").strip())
        return jsonify({"success": True, "message": "Category created.", "category_id": category_id}), 201

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
    return jsonify({"success": True, "categories": categories})
