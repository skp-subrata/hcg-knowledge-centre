"""Assessments, feedback and certificates - web and API paths agree."""
from pathlib import Path

import pytest

import app as app_module
from tests.helpers import assign, make_assessment


def _answers(question_ids, option):
	return {f"q{qid}": option for qid in question_ids}


@pytest.fixture
def course(world):
	"""A published course the 'student' user is assigned to and can take assessments on."""
	return world.mod_published_course_id


def _cert_record(db, user_id, course_id):
	rows = db("SELECT * FROM course_certifications WHERE user_id = ? AND course_id = ?", (user_id, course_id))
	return dict(rows[0]) if rows else None


# ---------------------------------------------------------------------------
# web assessment
# ---------------------------------------------------------------------------
def test_web_assessment_enforces_max_attempts(student, world, db, db_path, course):
	assessment_id, qids = make_assessment(db_path, course, max_attempts=1, questions=(("Q", "a", 1),))
	first = student.post(f"/assessments/{assessment_id}", data=_answers(qids, "b"))
	assert first.status_code == 302 and "/assessment/result/" in first.headers["Location"]
	second = student.post(f"/assessments/{assessment_id}", data=_answers(qids, "a"), follow_redirects=True)
	assert b"used all 1 attempt" in second.data
	assert db("SELECT COUNT(*) AS n FROM assessment_attempts WHERE assessment_id = ?", (assessment_id,))[0]["n"] == 1


def test_first_attempt_pass_gets_a_real_badge(student, world, db, db_path, course):
	assessment_id, qids = make_assessment(db_path, course, questions=(("Q1", "a", 1), ("Q2", "a", 1)))
	student.post(f"/assessments/{assessment_id}", data=_answers(qids, "a"))
	record = _cert_record(db, world.users["student"], course)
	assert record["badge"] == "PLATINUM"
	assert record["latest_assessment_status"] == "FEEDBACK_PENDING"


def test_attempts_are_written_once_in_their_final_state(student, world, db, db_path, course):
	assessment_id, qids = make_assessment(db_path, course, questions=(("Q", "a", 1),))
	student.post(f"/assessments/{assessment_id}", data=_answers(qids, "a"))
	row = dict(db("SELECT * FROM assessment_attempts WHERE assessment_id = ?", (assessment_id,))[0])
	assert row["status"] == "submitted" and row["result"] == "pass" and row["score"] == 1 and row["submitted_at"]
	assert "'evaluated'" not in Path(app_module.__file__).read_text(encoding="utf-8")


def test_web_grading_ignores_option_case(student, world, db, db_path, course):
	assessment_id, qids = make_assessment(db_path, course, questions=(("Q", "B", 1),))  # upper-case key
	student.post(f"/assessments/{assessment_id}", data=_answers(qids, "b"))
	assert db("SELECT result FROM assessment_attempts WHERE assessment_id = ?", (assessment_id,))[0]["result"] == "pass"


def test_certified_learners_cannot_retake(make_client, world, db_path):
	maya = make_client("maya.student")
	assessment_id, qids = make_assessment(db_path, world.certified_course_id)
	response = maya.post(f"/assessments/{assessment_id}", data=_answers(qids, "a"), follow_redirects=True)
	assert b"already certified" in response.data


# ---------------------------------------------------------------------------
# admin forms
# ---------------------------------------------------------------------------
def test_blank_pass_percentage_and_attempts_default(admin, world, db, course):
	response = admin.post("/admin", data={
		"action": "add_assessment", "course_id": course, "assessment_type": "post",
		"assessment_title": "Blank Numbers", "pass_percentage": "", "max_attempts": "",
	})
	assert response.status_code in (200, 302)
	row = dict(db("SELECT * FROM assessments WHERE title = 'Blank Numbers'")[0])
	assert row["pass_percentage"] == 60 and row["max_attempts"] == 1
	assert db("SELECT typeof(pass_percentage) AS t FROM assessments WHERE id = ?", (row["id"],))[0]["t"] == "integer"
	admin.post("/admin", data={
		"action": "update_assessment", "record_id": row["id"], "title": "Blank Numbers", "type": "post",
		"pass_percentage": "abc", "max_attempts": "",
	})
	row = dict(db("SELECT * FROM assessments WHERE id = ?", (row["id"],))[0])
	assert row["pass_percentage"] == 60 and row["max_attempts"] == 1


def test_add_question_defaults_blank_marks_and_validates_the_answer(admin, world, db, db_path, course):
	assessment_id, _ = make_assessment(db_path, course, questions=())
	base = {"action": "add_question", "assessment_id": assessment_id, "question_text": "Q?",
	        "option_a": "1", "option_b": "2", "option_c": "3", "option_d": "4"}
	assert admin.post("/admin", data={**base, "correct_option": "B", "marks": ""}).status_code in (200, 302)
	row = dict(db("SELECT q.* FROM questions q JOIN assessment_questions aq ON aq.question_id = q.id WHERE aq.assessment_id = ?", (assessment_id,))[0])
	assert row["marks"] == 1 and row["correct_option"] == "b"
	response = admin.post("/admin", data={**base, "question_text": "Bad", "correct_option": "z", "marks": "2"}, follow_redirects=True)
	assert b"must be A, B, C or D" in response.data
	assert not db("SELECT 1 FROM questions WHERE question_text = 'Bad'")


# ---------------------------------------------------------------------------
# feedback and certificates
# ---------------------------------------------------------------------------
def test_pre_assessment_alone_does_not_certify_but_post_does(student, world, db, db_path, course):
	uid = world.users["student"]
	pre_id, pre_q = make_assessment(db_path, course, kind="pre", pass_percentage=60, questions=(("P", "a", 1),))
	post_id, post_q = make_assessment(db_path, course, kind="post", pass_percentage=90, questions=(("Q", "a", 1),))
	student.post(f"/assessments/{pre_id}", data=_answers(pre_q, "a"))
	assert _cert_record(db, uid, course)["latest_assessment_status"] != "FEEDBACK_PENDING"
	response = student.post(f"/course/{course}/feedback", data={"rating": "8", "comments": "great"}, follow_redirects=True)
	assert not db("SELECT 1 FROM certificates WHERE student_id = ? AND course_id = ?", (uid, course))
	student.post(f"/assessments/{post_id}", data=_answers(post_q, "a"))
	assert _cert_record(db, uid, course)["latest_assessment_status"] == "FEEDBACK_PENDING"
	response = student.post(f"/course/{course}/feedback", data={"rating": "8", "comments": "great"})
	assert response.status_code == 302 and "/certificate" in response.headers["Location"]
	record = _cert_record(db, uid, course)
	assert record["certification_status"] == "CERTIFIED"
	assert record["pass_mark"] == 90, "the pass mark must come from the assessment that was passed"
	assert record["badge"] == "PLATINUM"


def test_feedback_submission_redirects_to_the_certificate_not_back_to_itself(student, world, db, db_path, course):
	"""Regression test for a live production bug (ERR_TOO_MANY_REDIRECTS on /course/<id>/feedback
	after a real submission): feedback_form()'s success/already-certified redirects used
	safe_referrer(url_for("certificate", ...)), which prefers request.referrer whenever it's
	same-host. A real browser's Referer on this POST is the feedback page itself, so
	safe_referrer returned that instead of the certificate URL -- redirecting back to
	/course/<id>/feedback, which (now CERTIFIED) redirected to safe_referrer(certificate) again,
	looping forever. The certificate target is fixed and known regardless of where the user came
	from, so these three redirects now go straight to url_for("certificate", ...) unconditionally."""
	uid = world.users["student"]
	post_id, qids = make_assessment(db_path, course, questions=(("Q", "a", 1),))
	student.post(f"/assessments/{post_id}", data=_answers(qids, "a"))
	assert _cert_record(db, uid, course)["latest_assessment_status"] == "FEEDBACK_PENDING"

	feedback_url = f"/course/{course}/feedback"
	response = student.post(feedback_url, data={"rating": "8", "comments": "great"}, headers={"Referer": f"http://localhost{feedback_url}"})
	assert response.status_code == 302
	assert response.headers["Location"] == f"/course/{course}/certificate"

	# Re-hitting the (now already-certified) feedback page, again with a same-page referrer,
	# must also go straight to the certificate rather than looping back to itself.
	response = student.get(feedback_url, headers={"Referer": f"http://localhost{feedback_url}"})
	assert response.status_code == 302
	assert response.headers["Location"] == f"/course/{course}/certificate"


def test_feedback_uses_the_latest_passing_attempt(student, world, db, db_path, course):
	uid = world.users["student"]
	post_id, qids = make_assessment(db_path, course, pass_percentage=50, max_attempts=3, questions=(("Q1", "a", 1), ("Q2", "a", 1)))
	student.post(f"/assessments/{post_id}", data={f"q{qids[0]}": "a", f"q{qids[1]}": "b"})  # 50% pass
	student.post(f"/course/{course}/feedback", data={"rating": "7", "comments": "ok"})
	record = _cert_record(db, uid, course)
	assert record["assessment_score"] == 50 and record["pass_mark"] == 50 and record["badge"] == "BRONZE"


def test_certificates_are_unique_per_learner_and_course(student, anon, world, db, db_path, course):
	uid = world.users["student"]
	post_id, qids = make_assessment(db_path, course, questions=(("Q", "a", 1),))
	api = anon.post(f"/api/v1/assessments/{post_id}/submit", json={"answers": {str(qids[0]): "a"}}, headers=world.api_keys["student"])
	assert api.status_code == 201, api.get_json()
	first = db("SELECT cert_uid FROM certificates WHERE student_id = ? AND course_id = ?", (uid, course))
	assert len(first) == 1 and first[0]["cert_uid"].startswith(f"CERT-{course}-{uid}-")
	student.post(f"/course/{course}/feedback", data={"rating": "9", "comments": "great"})
	again = db("SELECT cert_uid FROM certificates WHERE student_id = ? AND course_id = ?", (uid, course))
	assert [r["cert_uid"] for r in again] == [first[0]["cert_uid"]]


def test_api_submit_certifies_like_the_web_path(student, anon, world, db, db_path, course):
	uid = world.users["student"]
	post_id, qids = make_assessment(db_path, course, questions=(("Q", "a", 1),))
	response = anon.post(f"/api/v1/assessments/{post_id}/submit", json={"answers": {str(qids[0]): "a"}}, headers=world.api_keys["student"])
	assert response.status_code == 201, response.get_json()
	record = _cert_record(db, uid, course)
	assert record and record["certification_status"] == "CERTIFIED" and record["badge"] == "PLATINUM"
	assert record["certificate_id"] == db("SELECT cert_uid FROM certificates WHERE student_id = ? AND course_id = ?", (uid, course))[0]["cert_uid"]
	assert student.get(f"/course/{course}/certificate").status_code == 200
	owner_rows = db("SELECT * FROM reward_transactions WHERE reward_source = 'COURSE_OWNER_RATING' AND user_id = ?", (world.users["mod"],))
	assert not owner_rows, "no owner rating reward without a real rating"
	assert len(db("SELECT * FROM reward_transactions WHERE reward_source = 'COURSE_CERTIFICATION' AND user_id = ?", (uid,))) == 1


def test_api_and_web_certification_share_one_reward_reference(student, anon, world, db, db_path, course):
	uid = world.users["student"]
	post_id, qids = make_assessment(db_path, course, questions=(("Q", "a", 1),))
	anon.post(f"/api/v1/assessments/{post_id}/submit", json={"answers": {str(qids[0]): "a"}}, headers=world.api_keys["student"])
	student.post(f"/course/{course}/feedback", data={"rating": "9", "comments": "great"})
	rows = db("SELECT points FROM reward_transactions WHERE reward_source = 'COURSE_CERTIFICATION' AND user_id = ?", (uid,))
	assert len(rows) == 1, "web feedback after an API certification must not pay the certification twice"


def test_certificate_page_exposes_elements_the_download_script_needs(make_client, world):
	maya = make_client("maya.student")
	html = maya.get(f"/course/{world.certified_course_id}/certificate").get_data(as_text=True)
	assert 'id="certificate-card"' in html and 'id="download-png-btn"' in html and 'id="download-pdf-btn"' in html
	assert "html2canvas" in html and "jspdf" in html.lower()
	assert "setTimeout(() => pngButton" not in html, "a plain page view must not auto-trigger the download"


def test_certificate_capture_pins_viewport_dependent_styles_and_tier_colors(make_client, world):
	"""Regression coverage for a live report: the downloaded PNG/PDF showed text and the stat
	grid slightly shifted from the on-screen page, and the gold/silver badge wasn't visible at
	all. Root causes, confirmed by directly diffing html2canvas's own raw output before/after
	(not just the on-screen DOM, which looked fine even before this fix): (1) html2canvas
	evaluates media queries/vw units against its own internal virtual window rather than the
	real one -- fixed by pinning every viewport-dependent rule to its widest state via
	.is-capturing, only for the instant of capture; (2) html2canvas 1.4.1 serializes the inline,
	CSS-class-styled <svg> badge into a standalone image with no access to app.css, so the whole
	badge -- not just its colour -- renders as blank space; fixed by swapping in a plain <img>
	(rendered to an offscreen <canvas> with the same resolved colours) just for the capture,
	since html2canvas handles <img> tags reliably."""
	maya = make_client("maya.student")
	html = maya.get(f"/course/{world.certified_course_id}/certificate").get_data(as_text=True)
	assert "captureCard" in html and "is-capturing" in html
	assert "resolveTierColors" in html and "--tier-1" in html and "--tier-2" in html
	assert "renderBadgeToDataURL" in html and "svgBadge" in html and "badgeImg" in html
	assert "cert-badge-glow" in html and "cert-badge-ring" in html and "cert-badge-fill" in html

	css = Path(app_module.__file__).resolve().parent.joinpath("static", "css", "app.css").read_text(encoding="utf-8")
	assert ".certificate.is-capturing" in css
	assert ".certificate.is-capturing .certificate-title" in css
	assert ".certificate.is-capturing .certificate-name" in css
	assert ".certificate.is-capturing dl" in css


@pytest.mark.parametrize("tier", ["PLATINUM", "GOLD", "SILVER", "BRONZE"])
def test_certificate_badge_uses_gradient_defs_namespaced_per_tier(tier, make_client, world, db):
	"""The badge's glow/ring/star each pull their colour from a <radialGradient>/<linearGradient>
	defined inline (see certificate_badge() in _macros.html), not a flat fill -- the gradient ids
	are namespaced by tier so two badges on one page (were this macro ever reused elsewhere)
	could never collide and silently point at the wrong tier's colours."""
	maya_id = world.users["maya.student"]
	db("UPDATE course_certifications SET badge = ? WHERE user_id = ? AND course_id = ?", (tier, maya_id, world.certified_course_id))
	maya = make_client("maya.student")
	html = maya.get(f"/course/{world.certified_course_id}/certificate").get_data(as_text=True)
	tier_lower = tier.lower()
	for prefix in ("cert-badge-glow-", "cert-badge-ring-", "cert-badge-fill-"):
		assert f'id="{prefix}{tier_lower}"' in html
		assert f'url(#{prefix}{tier_lower})' in html


def test_certificate_page_has_the_new_decorative_elements(make_client, world):
	"""Regression coverage for the visual refresh: a gradient/glow background, an inset double
	frame, a gradient title divider, a pill-styled tier label, and a drop-shadowed, gently
	animated badge -- all proven html2canvas-safe (plain CSS gradients/shadows/pseudo-elements,
	or the existing canvas-swap for the one inline <svg>), unlike a naive redesign that could
	easily have reintroduced the exact blank-badge/box-instead-of-line bugs fixed earlier."""
	maya = make_client("maya.student")
	html = maya.get(f"/course/{world.certified_course_id}/certificate").get_data(as_text=True)
	assert 'class="certificate-divider"' in html

	css = Path(app_module.__file__).resolve().parent.joinpath("static", "css", "app.css").read_text(encoding="utf-8")
	assert ".certificate::before" in css, "the inset double-frame pseudo-element"
	assert ".certificate-divider" in css and "linear-gradient" in css
	assert ".certificate-tier-label" in css and "border-radius: 999px" in css
	assert "cert-badge-breathe" in css
	assert "@media (prefers-reduced-motion: reduce)" in css and ".cert-badge-glow { animation: none; }" in css


def test_download_certificate_route_triggers_download_mode(make_client, world):
	maya = make_client("maya.student")
	response = maya.get(f"/course/{world.certified_course_id}/certificate/download")
	assert response.status_code == 200
	body = response.get_data(as_text=True)
	assert 'id="certificate-card"' in body and 'id="download-png-btn"' in body
	assert "setTimeout(() => pngButton && pngButton.click(), 800)" in body


@pytest.mark.parametrize("tier", ["PLATINUM", "GOLD", "SILVER", "BRONZE"])
def test_certificate_reflects_each_tier(tier, make_client, world, db):
	maya_id = world.users["maya.student"]
	db("UPDATE course_certifications SET badge = ? WHERE user_id = ? AND course_id = ?", (tier, maya_id, world.certified_course_id))
	maya = make_client("maya.student")
	html = maya.get(f"/course/{world.certified_course_id}/certificate").get_data(as_text=True)
	assert f'data-tier="{tier.lower()}"' in html
	assert tier.title() in html


def test_api_submit_requires_an_assignment_for_learners(anon, world, db_path):
	course_id = world.python_course_id  # 'student' is NOT assigned to Python Foundations
	post_id, qids = make_assessment(db_path, course_id, questions=(("Q", "a", 1),))
	response = anon.post(f"/api/v1/assessments/{post_id}/submit", json={"answers": {str(qids[0]): "a"}}, headers=world.api_keys["student"])
	assert response.status_code == 403
