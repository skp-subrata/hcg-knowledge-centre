"""Every template compiles and every page renders on the new base layout for the right persona."""
import re

import pytest
from flask import template_rendered

import app as app_module
from tests.helpers import make_assessment

PAGE_TEMPLATES = {
	"error.html",
	"index.html", "admin.html", "courses.html", "course.html", "assessment.html", "assessment_result.html",
	"assessment_review.html", "feedback.html", "certificate.html", "community_feed.html", "post_detail.html",
	"create_post.html", "edit_post.html", "my_posts.html", "approval_queue.html", "groups.html", "group_detail.html",
	"notifications.html", "profile.html", "rewards.html", "reward_admin.html", "reports.html",
	"master_management.html", "api_docs.html", "view_as.html",
}

# Pages already migrated to the design system: these must have exactly one <h1>, one <main>, and no bare focus:outline-none.
MIGRATED = {"error.html", "index.html", "courses.html", "course.html", "api_docs.html", "admin.html", "group_detail.html", "master_management.html", "reward_admin.html", "reports.html", "groups.html", "profile.html", "notifications.html", "rewards.html", "view_as.html", "community_feed.html", "post_detail.html", "create_post.html", "edit_post.html", "my_posts.html", "approval_queue.html", "assessment.html", "assessment_result.html", "assessment_review.html", "feedback.html", "certificate.html"}


def _feedback_pending(client, world, db_path):
	assessment_id, qids = make_assessment(db_path, world.mod_published_course_id, questions=(("Q", "a", 1),))
	client.post(f"/assessments/{assessment_id}", data={f"q{qids[0]}": "a"})


def _assessment_url(world, db_path):
	assessment_id, _ = make_assessment(db_path, world.mod_published_course_id, questions=(("Q", "a", 1),))
	return f"/assessments/{assessment_id}"


# (template, url or callable(world, db_path) -> url, persona, optional prepare(client, world, db_path))
CASES = [
	("index.html", "/", "anon", None),
	("index.html", "/", "student", None),
	("admin.html", "/admin", "admin", None),
	("courses.html", "/courses", "mod", None),
	("course.html", lambda w, d: f"/course/{w.mod_published_course_id}", "student", None),
	("assessment.html", _assessment_url, "student", None),
	("assessment_result.html", lambda w, d: f"/assessment/result/{w.attempt_id}", "maya", None),
	("assessment_review.html", lambda w, d: f"/assessment/review/{w.attempt_id}", "maya", None),
	("feedback.html", lambda w, d: f"/course/{w.mod_published_course_id}/feedback", "student", _feedback_pending),
	("certificate.html", lambda w, d: f"/course/{w.certified_course_id}/certificate", "maya", None),
	("community_feed.html", "/community", "student", None),
	("post_detail.html", lambda w, d: f"/community/post/{w.published_post_id}", "student", None),
	("create_post.html", "/community/create", "student", None),
	("edit_post.html", lambda w, d: f"/community/edit/{w.pending_post_id}", "student", None),
	("my_posts.html", "/community/my-posts", "student", None),
	("approval_queue.html", "/community/approval-queue", "mod", None),
	("groups.html", "/groups", "mod", None),
	("group_detail.html", lambda w, d: f"/groups/{w.group_id}", "mod", None),
	("notifications.html", "/notifications", "maya", None),
	("profile.html", "/profile", "student", None),
	("rewards.html", "/rewards", "maya", None),
	("reward_admin.html", "/admin/rewards", "admin", None),
	("reports.html", "/admin/reports", "admin", None),
	("master_management.html", "/admin/masters", "admin", None),
	("api_docs.html", "/api/v1/docs", "admin", None),
	("view_as.html", "/view-as", "admin", None),
]

RENDERED = set()


def _client_for(persona, make_client):
	return {
		"anon": lambda: make_client(),
		"student": lambda: make_client("student"),
		"maya": lambda: make_client("maya.student"),
		"mod": lambda: make_client("mod", "moderator"),
		"admin": lambda: make_client("admin", "admin"),
	}[persona]()


def test_every_template_compiles():
	env = app_module.app.jinja_env
	names = [name for name in env.list_templates() if name.endswith(".html")]
	assert PAGE_TEMPLATES <= set(names)
	for name in names:
		env.get_template(name)


@pytest.mark.parametrize("template,url,persona,prepare", CASES, ids=[f"{c[0]}[{c[2]}]" for c in CASES])
def test_page_renders_on_the_new_base(template, url, persona, prepare, world, db_path, make_client):
	client = _client_for(persona, make_client)
	if prepare:
		prepare(client, world, db_path)
	if callable(url):
		url = url(world, db_path)
	rendered = []
	receiver = lambda sender, template, context, **extra: rendered.append(template.name)
	template_rendered.connect(receiver, app_module.app)
	try:
		response = client.get(url)
	finally:
		template_rendered.disconnect(receiver, app_module.app)
	assert response.status_code == 200, f"{url} as {persona}: HTTP {response.status_code}"
	assert template in rendered, f"{url} rendered {rendered}, expected {template}"
	RENDERED.update(rendered)
	html = response.get_data(as_text=True)
	title = re.search(r"<title>(.*?)</title>", html, re.S)
	assert title and "<script" not in title.group(1), "no script inside <title>"
	assert "{{" not in html and "{%" not in html, "unrendered Jinja leaked into the page"
	assert 'id="toast-region"' in html and "/static/css/app.css" in html and "/static/js/app.js" in html
	assert html.count("<header") >= 1 and "material-toolbar" in html
	if template in MIGRATED:
		assert len(re.findall(r"<h1[\s>]", html)) == 1, "exactly one <h1> per page"
		assert html.count("<main") == 1, "exactly one <main> landmark"
		assert "focus:outline-none" not in html, "focus rings must not be removed"


@pytest.mark.parametrize("persona,url,code", [("anon", "/this-page-does-not-exist", 404), ("student", "/this-page-does-not-exist", 404), ("admin", "/logout", 405)])
def test_error_page_renders_on_the_new_base(persona, url, code, make_client):
	"""Browsers get the branded error page on the shared layout; the status code is preserved."""
	client = _client_for(persona, make_client)
	rendered = []
	receiver = lambda sender, template, context, **extra: rendered.append(template.name)
	template_rendered.connect(receiver, app_module.app)
	try:
		response = client.get(url)
	finally:
		template_rendered.disconnect(receiver, app_module.app)
	assert response.status_code == code
	assert "error.html" in rendered
	RENDERED.update(rendered)
	html = response.get_data(as_text=True)
	assert html.count("<h1") == 1 and html.count("<main") == 1
	assert "focus:outline-none" not in html and "{{" not in html
	assert str(code) in html and 'id="toast-region"' in html


@pytest.mark.parametrize("path,headers", [("/api/v1/does-not-exist", {}), ("/does-not-exist", {"X-Requested-With": "XMLHttpRequest"})])
def test_api_and_ajax_callers_get_json_errors(path, headers, anon):
	response = anon.get(path, headers=headers)
	assert response.status_code == 404 and response.is_json
	assert response.get_json()["status"] == 404


def test_all_page_templates_were_rendered_by_the_cases():
	"""Runs after the parametrised cases (pytest collects in file order)."""
	missing = PAGE_TEMPLATES - RENDERED
	assert not missing, f"no render case covers: {sorted(missing)}"


def test_static_assets_are_served(anon):
	css = anon.get("/static/css/app.css")
	js = anon.get("/static/js/app.js")
	assert css.status_code == 200 and "text/css" in css.content_type
	assert js.status_code == 200 and "javascript" in js.content_type
	assert "--c-accent" in css.get_data(as_text=True)
	assert "window.HKC" in js.get_data(as_text=True)


def test_logged_out_pages_do_not_include_the_drawer(anon):
	html = anon.get("/").get_data(as_text=True)
	assert 'id="drawer"' not in html and 'id="notification-list"' not in html


def test_logged_in_pages_include_navigation_release_notes_and_toasts(student):
	html = student.get("/").get_data(as_text=True)
	assert 'id="drawer"' in html and 'id="release-sheet"' in html and 'id="toast-region"' in html
	assert 'aria-label="Primary"' in html and 'data-theme-toggle' in html


def test_flash_categories_reach_the_toast(anon, login):
	response = login(anon, "admin", "wrong-password")
	html = response.get_data(as_text=True)
	assert 'data-kind="error"' in html and 'role="alert"' in html
