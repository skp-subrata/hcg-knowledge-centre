"""
Support Module Flask Blueprint (Controllers & Routes).
Mounts all frontend templates and RESTful API routes under /support and /api/support.
"""

from functools import wraps
from pathlib import Path
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, send_file, abort
)

def get_db():
    from app import get_db as _get_db
    return _get_db()

from support.models.schema import init_support_db
from support.config import SUPPORT_UPLOAD_DIR
from support.repositories import issue_repository, category_repository, audit_repository
from support.services import issue_service, tat_service, attachment_service
from support.validators import validate_create_issue_payload


support_bp = Blueprint(
    "support",
    __name__,
    template_folder="../templates",
    url_prefix=""
)


# Ensure DB schema tables exist when Blueprint is accessed
@support_bp.before_app_request
def ensure_support_tables_exist():
    """Lazily initialize support_* tables if missing."""
    if not getattr(support_bp, "_db_initialized", False):
        try:
            with get_db() as conn:
                init_support_db(conn)
            support_bp._db_initialized = True
        except Exception as e:
            print(f"[SupportBP] Error initializing support tables: {e}")


# ── AUTHENTICATION DECORATORS ──

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "Authentication required."}), 401
            flash("Please log in to access the Support & Helpdesk workspace.")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "Authentication required."}), 401
            flash("Authentication required.")
            return redirect(url_for("home"))

        # Check true actual_role or role
        is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"
        if not is_admin:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "Access restricted to administrators only."}), 403
            flash("Access restricted to administrators only.")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function


# ── FRONTEND UI ROUTES ──

@support_bp.route("/support", methods=["GET"])
@login_required
def user_dashboard():
    """User Support Dashboard - Shows user's reported issues."""
    user_id = session["user_id"]
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()

    category_id_val = int(category_id) if category_id and category_id.isdigit() else None

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
        issues_page = issue_repository.get_user_issues(
            conn, user_id=user_id, page=page, page_size=15,
            search=search, category_id=category_id_val,
            status_filter=status_filter, priority_filter=priority_filter
        )

        # User quick stats
        total = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND is_archived = 0", (user_id,)).fetchone()["cnt"]
        in_progress = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'IN_PROGRESS' AND is_archived = 0", (user_id,)).fetchone()["cnt"]
        awaiting = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'AWAITING_CONFIRMATION' AND is_archived = 0", (user_id,)).fetchone()["cnt"]
        resolved = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE reported_by_user_id = ? AND status = 'RESOLVED_CONFIRMED' AND is_archived = 0", (user_id,)).fetchone()["cnt"]

    stats = {
        "total": total,
        "in_progress": in_progress,
        "awaiting_confirmation": awaiting,
        "resolved": resolved
    }

    return render_template(
        "user_dashboard.html",
        issues_page=issues_page,
        categories=categories,
        stats=stats,
        current_search=search,
        current_category=category_id,
        current_status=status_filter,
        user=session.get("user"),
        role=session.get("role"),
        actual_role=session.get("actual_role")
    )


@support_bp.route("/support/report", methods=["GET", "POST"])
@login_required
def report_issue():
    """Report an Issue Screen & Submission Form."""
    user_id = session["user_id"]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category_id = request.form.get("category_id", type=int)
        module_name = request.form.get("module_name", "").strip()
        page_url = request.form.get("page_url", "").strip()
        device_info = request.form.get("device_info", "").strip()
        browser_info = request.form.get("browser_info", "").strip()
        os_info = request.form.get("os_info", "").strip()

        attachments = request.files.getlist("attachments")

        is_valid, errors = validate_create_issue_payload(title, description, category_id)
        if not is_valid:
            for err in errors:
                flash(err)
            return redirect(url_for("support.report_issue"))

        try:
            with get_db() as conn:
                issue = issue_service.create_new_issue(
                    conn,
                    user_id=user_id,
                    title=title,
                    description=description,
                    category_id=category_id,
                    module_name=module_name,
                    page_url=page_url,
                    device_info=device_info,
                    browser_info=browser_info,
                    os_info=os_info,
                    attachments=attachments
                )
            flash(f"Support ticket #{issue['issue_number']} created successfully!")
            return redirect(url_for("support.issue_detail", issue_id=issue["issue_id"]))
        except ValueError as ve:
            flash(str(ve))
            return redirect(url_for("support.report_issue"))
        except Exception as e:
            flash(f"Failed to submit issue: {e}")
            return redirect(url_for("support.report_issue"))

    # GET Request: Prepare user profile snapshot & active categories
    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
        u_row = conn.execute("SELECT full_name, employee_id, email, phone_number FROM users WHERE id = ?", (user_id,)).fetchone()

    user_snapshot = {
        "name": u_row["full_name"] if u_row else session.get("user", ""),
        "employee_id": u_row["employee_id"] if u_row else "",
        "email": u_row["email"] if u_row else "",
        "phone": u_row["phone_number"] if u_row else ""
    }

    return render_template(
        "create_issue.html",
        categories=categories,
        user_snapshot=user_snapshot,
        user=session.get("user"),
        role=session.get("role"),
        actual_role=session.get("actual_role")
    )


@support_bp.route("/support/issues/<int:issue_id>", methods=["GET"])
@login_required
def issue_detail(issue_id):
    """Issue Detail & Interactive Conversation Timeline."""
    user_id = session["user_id"]
    is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            flash("Support issue not found.")
            return redirect(url_for("support.user_dashboard"))

        # Authorization check: Admin OR issue reporter
        if not is_admin and issue["reported_by_user_id"] != user_id:
            flash("You are not authorized to view this support issue.")
            return redirect(url_for("support.user_dashboard"))

        updates = [dict(u) for u in issue_repository.get_issue_updates(conn, issue_id, include_internal=is_admin)]
        attachments = [dict(a) for a in issue_repository.get_issue_attachments(conn, issue_id)]
        tat = tat_service.calculate_issue_tat(issue)

    return render_template(
        "issue_detail.html",
        issue=dict(issue),
        updates=updates,
        attachments=attachments,
        tat=tat,
        is_admin=is_admin,
        current_user_id=user_id,
        user=session.get("user"),
        role=session.get("role"),
        actual_role=session.get("actual_role")
    )


@support_bp.route("/support/issues/<int:issue_id>/message", methods=["POST"])
@login_required
def post_issue_message(issue_id):
    """Post a message/comment to issue conversation."""
    user_id = session["user_id"]
    is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"
    message = request.form.get("message", "").strip()
    attachments = request.files.getlist("attachments")

    if not message and not any(f.filename for f in attachments if f):
        flash("Message content or file attachment is required.")
        return redirect(url_for("support.issue_detail", issue_id=issue_id))

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            flash("Issue not found.")
            return redirect(url_for("support.user_dashboard"))

        if not is_admin and issue["reported_by_user_id"] != user_id:
            flash("Unauthorized.")
            return redirect(url_for("support.user_dashboard"))

        issue_service.add_comment(conn, issue_id, user_id, message, is_internal=0, attachments=attachments)

    flash("Message posted to timeline.")
    return redirect(url_for("support.issue_detail", issue_id=issue_id))


# ── ADMIN FRONTEND ROUTES ──

@support_bp.route("/support/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    """Admin Support Panel Dashboard."""
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()

    category_id_val = int(category_id) if category_id and category_id.isdigit() else None

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn, active_only=False)]
        stats = issue_repository.get_support_dashboard_stats(conn)
        issues_page = issue_repository.get_admin_issues(
            conn, page=page, page_size=15, search=search,
            category_id=category_id_val, status_filter=status_filter,
            priority_filter=priority_filter
        )

    return render_template(
        "admin_dashboard.html",
        issues_page=issues_page,
        categories=categories,
        stats=stats,
        current_search=search,
        current_category=category_id,
        current_status=status_filter,
        current_priority=priority_filter,
        user=session.get("user"),
        role=session.get("role"),
        actual_role=session.get("actual_role")
    )


@support_bp.route("/support/admin/issues/<int:issue_id>/status", methods=["POST"])
@admin_required
def admin_update_status(issue_id):
    """Admin endpoint to update status."""
    new_status = request.form.get("status", "").strip()
    user_id = session["user_id"]

    try:
        with get_db() as conn:
            issue_service.update_status(conn, issue_id, new_status, user_id, is_admin=True)
        flash(f"Issue status updated to {new_status}.")
    except Exception as e:
        flash(f"Could not update status: {e}")

    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/issues/<int:issue_id>/priority", methods=["POST"])
@admin_required
def admin_update_priority(issue_id):
    """Admin endpoint to set priority."""
    new_priority = request.form.get("priority", "").strip()
    user_id = session["user_id"]

    try:
        with get_db() as conn:
            issue_service.update_priority(conn, issue_id, new_priority, user_id)
        flash(f"Issue priority updated to {new_priority}.")
    except Exception as e:
        flash(f"Could not update priority: {e}")

    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/issues/<int:issue_id>/resolution", methods=["POST"])
@admin_required
def admin_provide_resolution(issue_id):
    """Admin endpoint to submit resolution."""
    summary = request.form.get("summary", "").strip()
    details = request.form.get("details", "").strip()
    attachments = request.files.getlist("attachments")
    user_id = session["user_id"]

    if not summary or not details:
        flash("Resolution Summary and Details are required.")
        return redirect(url_for("support.issue_detail", issue_id=issue_id))

    try:
        with get_db() as conn:
            issue_service.provide_resolution(conn, issue_id, summary, details, user_id, attachments=attachments)
        flash("Resolution submitted to user for confirmation.")
    except Exception as e:
        flash(f"Could not submit resolution: {e}")

    return redirect(url_for("support.issue_detail", issue_id=issue_id))


@support_bp.route("/support/admin/reports", methods=["GET"])
@admin_required
def admin_reports():
    """Admin SLA & TAT Analytics Report Page."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE is_archived = 0").fetchone()["cnt"]
        resolved_cnt = conn.execute("SELECT COUNT(*) AS cnt FROM support_issues WHERE status = 'RESOLVED_CONFIRMED' AND is_archived = 0").fetchone()["cnt"]

        # Calculate average TAT metrics
        rows = conn.execute("SELECT * FROM support_issues WHERE is_archived = 0").fetchall()
        first_resp_secs = []
        resolution_secs = []
        confirmation_secs = []

        for r in rows:
            tat = tat_service.calculate_issue_tat(r)
            if tat["first_response_seconds"]: first_resp_secs.append(tat["first_response_seconds"])
            if tat["resolution_seconds"]: resolution_secs.append(tat["resolution_seconds"])
            if tat["confirmation_seconds"]: confirmation_secs.append(tat["confirmation_seconds"])

        avg_first_resp = (sum(first_resp_secs) / len(first_resp_secs)) if first_resp_secs else None
        avg_res = (sum(resolution_secs) / len(resolution_secs)) if resolution_secs else None
        avg_conf = (sum(confirmation_secs) / len(confirmation_secs)) if confirmation_secs else None

        # Category Breakdown
        cat_rows = conn.execute("""
            SELECT c.name, COUNT(i.issue_id) AS cnt
            FROM support_categories c
            LEFT JOIN support_issues i ON i.category_id = c.id AND i.is_archived = 0
            GROUP BY c.id ORDER BY cnt DESC
        """).fetchall()

        cat_breakdown = []
        for cr in cat_rows:
            cnt = cr["cnt"]
            pct = round((cnt / total * 100), 1) if total > 0 else 0
            cat_breakdown.append({"name": cr["name"], "count": cnt, "percentage": pct})

        # Priority Breakdown
        prio_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        p_rows = conn.execute("SELECT priority, COUNT(*) AS cnt FROM support_issues WHERE is_archived = 0 GROUP BY priority").fetchall()
        for pr in p_rows:
            if pr["priority"] in prio_counts:
                prio_counts[pr["priority"]] = pr["cnt"]

        res_rate = round((resolved_cnt / total * 100), 1) if total > 0 else 0

    report = {
        "total_issues": total,
        "resolved_issues": resolved_cnt,
        "resolution_rate": res_rate,
        "avg_first_response_tat": tat_service.format_duration(avg_first_resp),
        "avg_resolution_tat": tat_service.format_duration(avg_res),
        "avg_confirmation_tat": tat_service.format_duration(avg_conf),
        "category_breakdown": cat_breakdown,
        "categories_count": len(cat_breakdown),
        "priority_breakdown": prio_counts
    }

    return render_template(
        "admin_reports.html",
        report=report,
        user=session.get("user"),
        role=session.get("role"),
        actual_role=session.get("actual_role")
    )


# ── SECURE ATTACHMENT ACCESS ROUTE ──

@support_bp.route("/api/support/attachments/file/<int:issue_id>/<filename>", methods=["GET"])
@login_required
def serve_attachment_file(issue_id, filename):
    """
    Secure file streaming endpoint.
    Verifies user ownership or admin rights before streaming file.
    """
    user_id = session["user_id"]
    is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            return jsonify({"success": False, "message": "Issue not found."}), 404

        if not is_admin and issue["reported_by_user_id"] != user_id:
            return jsonify({"success": False, "message": "Forbidden access to file attachment."}), 403

    target_dir = SUPPORT_UPLOAD_DIR / str(issue_id)
    file_path = target_dir / filename

    if not file_path.exists() or not file_path.is_file():
        return jsonify({"success": False, "message": "Attachment file not found."}), 404

    return send_file(file_path, download_name=filename)


# ── REST APIS ──

@support_bp.route("/api/support/issues", methods=["GET", "POST"])
@login_required
def api_user_issues():
    """REST API for user issue listing & creation."""
    user_id = session["user_id"]

    if request.method == "POST":
        data = request.get_json() or request.form
        title = data.get("title", "").strip()
        description = data.get("description", "").strip()
        category_id = data.get("category_id")

        if category_id and str(category_id).isdigit():
            category_id = int(category_id)

        is_valid, errors = validate_create_issue_payload(title, description, category_id)
        if not is_valid:
            return jsonify({"success": False, "errors": errors, "message": errors[0]}), 400

        try:
            with get_db() as conn:
                issue = issue_service.create_new_issue(
                    conn,
                    user_id=user_id,
                    title=title,
                    description=description,
                    category_id=category_id,
                    module_name=data.get("module_name", ""),
                    page_url=data.get("page_url", ""),
                    device_info=data.get("device_info", ""),
                    browser_info=data.get("browser_info", ""),
                    os_info=data.get("os_info", "")
                )
            return jsonify({"success": True, "message": "Issue created.", "issue": dict(issue)}), 201
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    # GET: List user's issues
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()

    with get_db() as conn:
        res = issue_repository.get_user_issues(conn, user_id=user_id, page=page, search=search)

    return jsonify({"success": True, **res})


@support_bp.route("/api/support/issues/<int:issue_id>", methods=["GET"])
@login_required
def api_get_issue_detail(issue_id):
    """REST API for fetching single issue details & timeline."""
    user_id = session["user_id"]
    is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"

    with get_db() as conn:
        issue = issue_repository.get_issue_by_id(conn, issue_id)
        if not issue:
            return jsonify({"success": False, "message": "Issue not found."}), 404

        if not is_admin and issue["reported_by_user_id"] != user_id:
            return jsonify({"success": False, "message": "Access forbidden."}), 403

        updates = [dict(u) for u in issue_repository.get_issue_updates(conn, issue_id, include_internal=is_admin)]
        attachments = [dict(a) for a in issue_repository.get_issue_attachments(conn, issue_id)]
        tat = tat_service.calculate_issue_tat(issue)

    return jsonify({
        "success": True,
        "issue": dict(issue),
        "updates": updates,
        "attachments": attachments,
        "tat": tat
    })


@support_bp.route("/api/support/issues/<int:issue_id>/confirm-resolution", methods=["POST"])
@login_required
def api_confirm_resolution(issue_id):
    """User confirms resolution."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    comment = data.get("comment", "").strip()

    try:
        with get_db() as conn:
            issue = issue_service.confirm_resolution(conn, issue_id, user_id, comment=comment)
        return jsonify({"success": True, "message": "Resolution confirmed.", "status": issue["status"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@support_bp.route("/api/support/issues/<int:issue_id>/reopen", methods=["POST"])
@login_required
def api_reopen_issue(issue_id):
    """User rejects resolution & reopens issue."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()

    try:
        with get_db() as conn:
            issue = issue_service.reopen_issue_flow(conn, issue_id, user_id, reason=reason)
        return jsonify({"success": True, "message": "Issue reopened.", "status": issue["status"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@support_bp.route("/api/support/categories", methods=["GET", "POST"])
@login_required
def api_categories():
    """Get active categories OR add a new category (Admin)."""
    if request.method == "POST":
        is_admin = session.get("actual_role") == "admin" or session.get("role") == "admin"
        if not is_admin:
            return jsonify({"success": False, "message": "Admin authorization required."}), 403

        data = request.get_json() or request.form
        name = data.get("name", "").strip()
        code = data.get("code", "").strip()
        desc = data.get("description", "").strip()

        if not name or not code:
            return jsonify({"success": False, "message": "Category name and code are required."}), 400

        try:
            with get_db() as conn:
                cat_id = category_repository.create_category(conn, name, code, desc)
            return jsonify({"success": True, "message": "Category created.", "category_id": cat_id}), 201
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    with get_db() as conn:
        categories = [dict(c) for c in category_repository.get_all_categories(conn)]
    return jsonify({"success": True, "categories": categories})


@support_bp.route("/api/support/admin/issues", methods=["GET"])
@admin_required
def api_admin_issues():
    """Admin REST API for issue management & search."""
    page = max(1, request.args.get("page", 1, type=int))
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()

    with get_db() as conn:
        res = issue_repository.get_admin_issues(
            conn, page=page, search=search,
            status_filter=status_filter, priority_filter=priority_filter
        )
    return jsonify({"success": True, **res})
