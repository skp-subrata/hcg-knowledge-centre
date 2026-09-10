"""Reports & analytics: the enhanced dashboard ported from origin/master.

get_reports_analytics_data() (app.py) backs both admin_reports() (the page) and
GET /api/admin/reports/analytics (the JSON the date-range filter fetches without a
reload). Support module data reuses support.repositories.issue_repository's own
get_support_dashboard_stats() rather than porting master's incompatible query.
"""
import app as app_module


def test_admin_reports_renders_for_every_preset(moderator, world):
	for preset in ("all", "today", "7d", "30d", "90d", "this_year"):
		response = moderator.get(f"/admin/reports?preset={preset}")
		assert response.status_code == 200, preset
		assert b"Reports" in response.data


def test_admin_reports_accepts_a_custom_date_range(moderator, world):
	response = moderator.get("/admin/reports?start_date=2020-01-01&end_date=2020-12-31")
	assert response.status_code == 200


def test_analytics_api_returns_the_expected_shape(moderator, world):
	response = moderator.get("/api/admin/reports/analytics")
	assert response.status_code == 200
	payload = response.get_json()
	for key in (
		"total_users", "active_users", "total_courses", "active_courses", "pass_rate",
		"total_points_issued", "chart_categories", "chart_completions", "progress_counts",
		"community_metrics", "reward_breakdown", "support_counts", "top_learners", "recent_activity",
	):
		assert key in payload, key
	# support_counts comes from the Support module's own dashboard-stats query
	for key in ("total", "open", "in_progress", "resolved", "critical", "high"):
		assert key in payload["support_counts"], key


def test_analytics_api_denies_non_staff(student, anon):
	assert student.get("/api/admin/reports/analytics").status_code in (302, 403)
	assert anon.get("/api/admin/reports/analytics").status_code in (302, 403)


def test_top_learners_only_counts_certified_records(moderator, world, db):
	# a non-certified course_certifications row must never appear on the leaderboard
	db("INSERT INTO course_certifications (user_id, course_id, user_name, course_name, certification_status) "
	   "VALUES (?, ?, 'Not Certified Yet', 'World Draft Course', 'FEEDBACK_PENDING')",
	   (world.users["student"], world.mod_draft_course_id))
	payload = moderator.get("/api/admin/reports/analytics").get_json()
	names = [row["user_name"] for row in payload["top_learners"]]
	assert "Not Certified Yet" not in names


def test_csv_download_cards_are_admin_only(admin, moderator):
	admin_html = admin.get("/admin/reports").get_data(as_text=True)
	assert "Reports &amp; downloads" in admin_html or "Reports & downloads" in admin_html
	assert "content-master/download" in admin_html

	moderator_html = moderator.get("/admin/reports").get_data(as_text=True)
	assert "content-master/download" not in moderator_html


def test_every_csv_download_route_referenced_exists_in_the_url_map():
	import re
	source = __import__("pathlib").Path(app_module.__file__).read_text(encoding="utf-8")
	template = __import__("pathlib").Path("templates/reports.html").read_text(encoding="utf-8")
	endpoints = re.findall(r"url_for\('(download_\w+_report)'\)", template)
	assert endpoints, "expected the reports template to reference the CSV download endpoints"
	registered = {rule.endpoint for rule in app_module.app.url_map.iter_rules()}
	for endpoint in endpoints:
		assert endpoint in registered, endpoint
