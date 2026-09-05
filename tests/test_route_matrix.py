"""Route x role smoke matrix.

Every URL rule is hit as every applicable persona with a minimal valid request.
Each endpoint declares a POLICY (the minimum role allowed). The test fails when:

* any response is a 5xx (the body / logged exception is included in the message);
* a persona below the minimum role is NOT denied (over-permissive route);
* a persona at or above the minimum role is denied with 401/403 (unless listed in MAY_DENY,
  e.g. "self or staff" routes hit with someone else's id);
* an endpoint has no POLICY row (every new route must declare its access rule).

Denial on the web surface is a redirect to "/" (the app never returns 403 there).

Known defects live in KNOWN_ISSUES keyed by (endpoint, method, persona): they xfail, and the
test FAILS as soon as one is fixed so the entry gets removed.
"""
import io
import re

import pytest
from flask import got_request_exception

import app as app_module
from tests.helpers import MATRIX_RESULTS, FakeHTTPResponse

WEB_PERSONAS = ("anon", "student", "mod", "admin", "imp_admin")
API_PERSONAS = ("anon", "api_student", "api_mod", "api_admin")

RANK = {"public": 0, "login": 1, "staff": 2, "admin": 3, "api_any": 1, "api_staff": 2, "api_admin": 3}
PERSONA_RANK = {
	"anon": 0, "student": 1, "imp_admin": 1, "mod": 2, "admin": 3,
	"api_student": 1, "api_mod": 2, "api_admin": 3,
}

# Not part of the generic sweep: session-mutating GETs and the duplicate /admin/reports rule.
EXCLUDED = {"static", "reports", "logout", "switch_role", "exit_view", "view_as"}

# endpoint -> minimum role. "api_*" policies put the endpoint on the API surface.
POLICY = {
	# public
	"home": "public", "get_departments_api": "public", "get_interests": "public",
	"api_get_unread_notifications": "public", "get_active_release": "public",
	# any logged-in user
	"create_interest": "login", "api_mark_notification_read": "login", "get_user_interests": "login",
	"add_user_interest": "login", "delete_user_interest": "login",
	"assessment_result": "login", "assessment_review": "login", "assessment": "login",
	"community_feed": "login", "create_post": "login", "my_posts": "login", "post_detail": "login",
	"comment_post": "login", "rate_post": "login", "edit_post": "login", "delete_post": "login",
	"course_detail": "login", "certificate": "login", "download_certificate": "login",
	"complete_course": "login", "feedback_form": "login",
	"notifications_page": "login", "mark_read": "login", "mark_all_read": "login",
	"profile": "login", "rewards_dashboard": "login", "proxy_embed": "login", "uploaded_file": "login",
	# staff (admin or moderator)
	"admin_panel": "staff", "delete_record": "staff", "download_question_template": "staff",
	"admin_reports": "staff", "download_assessment_questions": "staff",
	"approval_queue": "staff", "approval_action": "staff",
	"courses_page": "staff", "courses_create": "staff", "courses_update": "staff", "courses_publish": "staff",
	"groups_page": "staff", "group_detail": "staff", "add_group_members": "staff", "remove_group_member": "staff",
	"assign_group_course": "staff", "upload_group_members": "staff", "download_group_template": "staff",
	# admin only
	"download_api_credentials": "admin", "master_management": "admin", "api_docs_playground": "admin", "view_as_page": "admin",
	"admin_rewards": "admin", "admin_adjust_rewards": "admin", "admin_reset_rewards": "admin",
	"admin_settle_rewards": "admin", "admin_update_reward_source": "admin",
	"add_group_moderator": "admin", "remove_group_moderator": "admin", "toggle_group_moderator": "admin",
	"get_admin_api_credentials_api": "admin", "get_admin_assessments_api": "admin",
	"get_admin_courses_api": "admin", "get_admin_users_api": "admin",
	"download_assessment_results_report": "admin", "download_community_content_rewards_report": "admin",
	"download_content_approval_report": "admin", "download_content_engagement_report": "admin",
	"download_content_master_report": "admin", "download_course_owner_rewards_report": "admin",
	"download_reward_sources_report": "admin", "download_reward_transactions_report": "admin",
	"download_user_content_report": "admin", "download_user_rewards_report": "admin",
	# API v1 (header auth)
	"api_get_assessment": "api_any", "api_submit_assessment": "api_any",
	"api_get_attempt": "api_any", "api_get_attempt_review": "api_any",
	"api_list_courses": "api_any", "api_get_course": "api_any", "api_create_course": "api_staff", "api_assign_course": "api_staff",
	"api_add_department": "api_any", "api_add_position": "api_any", "api_add_location": "api_any",
	"api_get_groups": "api_any", "api_get_leaderboard": "api_any",
	"api_list_posts": "api_any", "api_create_post": "api_any", "api_get_post": "api_any",
	"api_comment_post": "api_any", "api_rate_post": "api_any",
	"api_get_reward_balance": "api_any", "api_get_reward_transactions": "api_any",
	"api_adjust_rewards": "api_admin", "api_reset_rewards": "api_admin", "api_settle_rewards": "api_admin",
	"api_list_users": "api_staff", "api_create_user": "api_admin", "api_get_user": "api_any",
	"api_download_user_data": "api_any", "api_update_user": "api_admin", "api_delete_user": "api_admin",
}

# "self or staff" routes are hit with maya's id, so these personas may legitimately be denied.
MAY_DENY = {
	# elevated admins are deliberately blocked from learner actions (app.py assessment/complete/feedback gates)
	"assessment": {"admin"}, "complete_course": {"admin"}, "feedback_form": {"admin"},
	# attempt pages belong to maya; everyone else is refused (imp_admin IS maya, so it passes)
	"assessment_result": {"student", "mod", "admin"}, "assessment_review": {"student", "mod", "admin"},
	"add_user_interest": {"student", "mod"},
	"delete_user_interest": {"student", "mod"},
	"api_submit_assessment": {"api_student"},  # not assigned to the course used by the matrix
	"api_get_attempt": {"api_student"},
	"api_get_attempt_review": {"api_student"},
	"api_get_user": {"api_student"},
	"api_download_user_data": {"api_student"},
}

# (endpoint, method, persona) -> QA id. Each xfails; the test fails once the defect is fixed.
KNOWN_ISSUES = {}  # (endpoint, method, persona) -> QA id; empty means every known defect is fixed


def _surface(endpoint):
	return "api" if POLICY.get(endpoint, "").startswith("api_") else "web"


def _rules():
	rules = []
	for rule in app_module.app.url_map.iter_rules():
		if rule.endpoint in EXCLUDED:
			continue
		for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
			rules.append((rule.endpoint, rule.rule, method))
	return sorted(set(rules))


RULES = _rules()
CASES = [
	(endpoint, rule, method, persona)
	for endpoint, rule, method in RULES
	for persona in (API_PERSONAS if _surface(endpoint) == "api" else WEB_PERSONAS)
]


def _case_id(case):
	endpoint, rule, method, persona = case
	return f"{method} {rule} [{persona}]"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def smoke_mode(monkeypatch):
	"""Return 500s instead of raising, and remember the exception for the failure message."""
	monkeypatch.setitem(app_module.app.config, "TESTING", False)
	monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)
	monkeypatch.setattr(app_module.app.logger, "disabled", True)  # 500s are expected for known defects
	captured = []

	def _remember(sender, exception, **extra):
		captured.append(f"{type(exception).__name__}: {exception}")

	got_request_exception.connect(_remember, app_module.app)
	yield captured
	got_request_exception.disconnect(_remember, app_module.app)


@pytest.fixture
def fake_network(monkeypatch):
	"""proxy_embed needs a response object; conftest's blocker would turn it into a false 500."""
	import urllib.request

	monkeypatch.setattr(urllib.request, "urlopen", lambda req, *a, **k: FakeHTTPResponse(getattr(req, "full_url", str(req))))
	import socket

	monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, proto=None, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))])


@pytest.fixture
def clients(db_path, make_client, world):
	def _client(persona):
		if persona == "anon" or persona.startswith("api_"):
			return app_module.app.test_client()
		if persona == "student":
			return make_client("student")
		if persona == "mod":
			return make_client("mod", "moderator")
		if persona == "admin":
			return make_client("admin", "admin")
		if persona == "imp_admin":
			client = make_client("maya.student")
			with client.session_transaction() as sess:
				sess["impersonator_id"] = world.users["admin"]
				sess["actual_role"] = "admin"
				sess["role"] = "basic user"
			return client
		raise ValueError(persona)

	return _client


def _headers(persona, world):
	if persona.startswith("api_"):
		return world.api_keys[persona[4:]]
	return {}


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------
def _param(name, endpoint, world):
	u = world.users
	if name == "course_id":
		if endpoint in ("courses_publish", "courses_update"):
			return world.mod_draft_course_id
		if endpoint in ("certificate", "download_certificate", "complete_course"):
			return world.certified_course_id
		return world.python_course_id
	if name == "assessment_id":
		return world.post_assessment_id
	if name == "attempt_id":
		return world.attempt_id
	if name == "post_id":
		if endpoint in ("approval_action", "edit_post", "delete_post"):
			return world.pending_post_id
		return world.published_post_id
	if name == "group_id":
		return world.group_id
	if name == "user_id":
		if endpoint in ("remove_group_moderator", "toggle_group_moderator"):
			return u["mod"]
		if endpoint == "api_delete_user":
			return u["rohan.student"]
		return u["maya.student"]
	if name == "target_user_id":
		return u["maya.student"]
	if name == "notif_id":
		return world.notification_id
	if name == "interest_id":
		return world.interest_id
	if name == "resource":
		return "course"
	if name == "record_id":
		return world.mod_draft_course_id
	if name == "filename":
		return world.upload_name
	raise KeyError(f"no value for path parameter {name!r} on {endpoint}")


def _url(endpoint, rule, method, world):
	values = {name: _param(name, endpoint, world) for name in rule.arguments}
	adapter = app_module.app.url_map.bind("localhost")
	url = adapter.build(endpoint, values, method=method)
	if endpoint == "proxy_embed":
		url += "?url=https://example.com/course"  # the world's published course content_url
	return url


def _request_kwargs(endpoint, method, world, db):
	"""Minimal valid body for state-changing routes. Returns kwargs for client.open()."""
	u = world.users
	maya, student = u["maya.student"], u["student"]
	if method == "GET":
		return {}
	form = {
		"home": {"username": "maya.student", "password": "learn123"},
		"admin_panel": {"action": "add_bank", "bank_name": "Smoke Bank", "category": "General"},
		"master_management": {"action": "add_interest", "interest_name": "Smoke Interest"},
		"admin_adjust_rewards": {"user_id": maya, "points": "5", "remarks": "smoke"},
		"admin_settle_rewards": {"user_id": maya, "points": "1", "remarks": "smoke"},
		"admin_reset_rewards": {"user_id": maya, "confirm": "YES"},
		"admin_update_reward_source": {"name": "RATING_GIVEN", "status": "active", "calculation_type": "FIXED", "multiplier": "0", "fixed_points": "2"},
		"approval_action": {"action": "APPROVE", "comments": "looks good"},
		"create_post": {"title": "Smoke Post", "description": "<p>hello</p>", "content_type": "Text/Article", "category": "General", "topic_tag": "", "status": "DRAFT"},
		"edit_post": {"title": "Smoke Post Edited", "description": "<p>hello</p>", "content_type": "Text/Article", "category": "General", "topic_tag": "", "status": "DRAFT"},
		"comment_post": {"comment_text": "smoke comment"},
		"rate_post": {"rating": "4"},
		"feedback_form": {"rating": "8", "comments": "smoke feedback"},
		"courses_create": {"name": "Smoke Course", "description": "", "category": "General", "status": "draft", "source_type": "url", "content_url": "", "difficulty": "beginner", "duration_minutes": "0", "tags": "", "thumbnail_color": "#6366f1"},
		"courses_update": {"name": "World Draft Course", "description": "draft", "category": "Testing", "status": "draft", "source_type": "url", "content_url": "https://example.com", "difficulty": "beginner", "duration_minutes": "10", "tags": "", "thumbnail_color": "#6366f1"},
		"groups_page": {"name": "Smoke Group", "description": "", "group_type": "team", "status": "active", "selected_users": [str(student)]},
		"assign_group_course": {"course_id": world.python_course_id},
		"add_group_members": {"selected_users": [str(maya)]},
		"add_group_moderator": {"moderator_id": u["aarav.moderator"]},
		"remove_group_member": {"user_id": student},
		"profile": {"full_name": "Smoke Name", "email": "smoke@example.com", "phone_number": "1234567890", "employee_id": "EMP-SMOKE", "department_id": world.department_id, "position_id": "1", "location_id": world.location_id, "about_me": "hi"},
		"complete_course": {}, "courses_publish": {}, "delete_record": {}, "delete_post": {},
		"mark_read": {}, "mark_all_read": {}, "api_mark_notification_read": {},
		"remove_group_moderator": {}, "toggle_group_moderator": {},
	}
	if endpoint == "assessment":
		qids = [row["question_id"] for row in db("SELECT question_id FROM assessment_questions WHERE assessment_id = ?", (world.post_assessment_id,))]
		return {"data": {f"q{qid}": "a" for qid in qids}}
	if endpoint == "upload_group_members":
		csv = b"Employee ID,User Name,Email,User Role\nEMP-0007,sampleuser007,,basic user\n"
		return {"data": {"group_id": str(world.group_id), "members_file": (io.BytesIO(csv), "members.csv")}, "content_type": "multipart/form-data"}
	if endpoint in form:
		return {"data": form[endpoint]}
	payload = {
		"create_interest": {"interest_name": "Smoke Interest"},
		"add_user_interest": {"interest_id": world.interest_id},
		"api_submit_assessment": {"answers": {str(row["question_id"]): "a" for row in db("SELECT question_id FROM assessment_questions WHERE assessment_id = ?", (world.post_assessment_id,))}},
		"api_create_course": {"name": "Smoke API Course", "content_type": "URL", "content_url": "https://example.com", "status": "draft"},
		"api_assign_course": {"student_id": student},
		"api_add_department": {"name": "Smoke Department"},
		"api_add_position": {"name": "Smoke Position"},
		"api_add_location": {"name": "Smoke Location"},
		"api_create_post": {"title": "Smoke API Post", "description": "<p>hello</p>", "content_type": "Text/Article"},
		"api_comment_post": {"comment": "smoke comment"},
		"api_rate_post": {"rating": 4},
		"api_adjust_rewards": {"target_user_id": maya, "points": 5, "description": "smoke"},
		"api_reset_rewards": {"target_user_id": maya},
		"api_settle_rewards": {"target_user_id": maya, "points": 1},
		"api_create_user": {"username": "smoke.user", "full_name": "Smoke User", "password": "secret123", "role": "basic user"},
		"api_update_user": {"full_name": "Renamed By Smoke"},
		"api_delete_user": {}, "delete_user_interest": {},
	}
	if endpoint in payload:
		return {"json": payload[endpoint]}
	raise KeyError(f"no request body defined for {method} {endpoint}")


def _classify(response):
	status = response.status_code
	if status >= 500:
		return "ERROR"
	if status in (401, 403):
		return "DENY"
	if status == 302:
		location = response.headers.get("Location", "")
		path = location.split("://", 1)[-1].split("/", 1)[-1] if "://" in location else location.lstrip("/")
		if path.strip("/") == "":
			return "DENY"  # redirected to home = the app's way of saying no
	return "OK"


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_every_endpoint_declares_a_policy():
	endpoints = {rule.endpoint for rule in app_module.app.url_map.iter_rules()} - EXCLUDED
	missing = sorted(endpoints - set(POLICY))
	assert not missing, f"add these endpoints to POLICY: {missing}"
	unknown = sorted(set(POLICY) - endpoints)
	assert not unknown, f"POLICY names endpoints that no longer exist: {unknown}"


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_route_matrix(case, world, clients, db, smoke_mode, fake_network):
	endpoint, rule_str, method, persona = case
	rule = next(r for r in app_module.app.url_map.iter_rules() if r.endpoint == endpoint and r.rule == rule_str)
	url = _url(endpoint, rule, method, world)
	kwargs = _request_kwargs(endpoint, method, world, db)
	client = clients(persona)
	response = client.open(url, method=method, headers=_headers(persona, world), **kwargs)
	MATRIX_RESULTS.setdefault((rule_str, method), {})[persona] = response.status_code

	policy = POLICY[endpoint]
	verdict = _classify(response)
	allowed = PERSONA_RANK[persona] >= RANK[policy]
	if policy == "public":
		ok = verdict != "ERROR"
	elif allowed:
		ok = verdict == "OK" or (verdict == "DENY" and persona in MAY_DENY.get(endpoint, ()))
	else:
		ok = verdict == "DENY"

	detail = f"{method} {url} as {persona}: HTTP {response.status_code} ({verdict}); policy={policy}, allowed={allowed}"
	if verdict == "ERROR":
		detail += f"; exception={smoke_mode[-1] if smoke_mode else response.get_data(as_text=True)[:200]!r}"

	key = (endpoint, method, persona)
	if key in KNOWN_ISSUES:
		if ok:
			pytest.fail(f"{KNOWN_ISSUES[key]} looks fixed - remove it from KNOWN_ISSUES. {detail}")
		pytest.xfail(f"{KNOWN_ISSUES[key]}. {detail}")
	assert ok, detail


INT_RULES = [(e, r, m) for e, r, m in RULES if "<int:" in r]


@pytest.mark.parametrize("endpoint,rule_str,method", INT_RULES, ids=lambda v: v if isinstance(v, str) else str(v))
def test_unknown_ids_do_not_crash(endpoint, rule_str, method, world, clients, db, smoke_mode, fake_network):
	"""A nonexistent id must give 302/400/404, never a 500."""
	rule = next(r for r in app_module.app.url_map.iter_rules() if r.endpoint == endpoint and r.rule == rule_str)
	int_names = set(re.findall(r"<int:(\w+)>", rule.rule))
	values = {name: (999999 if name in int_names else _param(name, endpoint, world)) for name in rule.arguments}
	url = app_module.app.url_map.bind("localhost").build(endpoint, values, method=method)
	persona = "api_admin" if _surface(endpoint) == "api" else "admin"
	kwargs = _request_kwargs(endpoint, method, world, db)
	response = clients(persona).open(url, method=method, headers=_headers(persona, world), **kwargs)
	detail = f"{method} {url} as {persona}: HTTP {response.status_code}"
	if response.status_code >= 500:
		detail += f"; exception={smoke_mode[-1] if smoke_mode else ''!r}"
	key = (endpoint, method, "unknown-id")
	if key in KNOWN_ISSUES:
		if response.status_code < 500:
			pytest.fail(f"{KNOWN_ISSUES[key]} looks fixed - remove it. {detail}")
		pytest.xfail(f"{KNOWN_ISSUES[key]}. {detail}")
	assert response.status_code < 500, detail


def test_upload_path_traversal_is_blocked(world, clients):
	response = clients("student").get("/uploads/..%2Fapp.py")
	assert response.status_code == 404
