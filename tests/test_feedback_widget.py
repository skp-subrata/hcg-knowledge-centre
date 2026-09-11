"""The floating 'send feedback' button: files a real Support & Helpdesk ticket via a JSON POST
to /api/support/quick-feedback (see tests/test_support.py for the endpoint's own behavior).
These tests pin what the button/sheet expose to the page and to app.js -- identity is always
captured server-side now (same as the full /support/report form), so there's no opt-in checkbox
for it any more, and nothing here talks to GitHub directly from the browser."""
from pathlib import Path

import app as app_module

ROOT = Path(app_module.__file__).resolve().parent


def test_the_widget_is_present_for_a_signed_in_user(student):
	html = student.get("/").get_data(as_text=True)
	assert 'data-dialog-open="feedback-sheet"' in html
	assert 'id="feedback-form"' in html
	assert 'id="feedback-title"' in html and 'id="feedback-details"' in html
	# identity is captured server-side unconditionally (like /support/report already does) --
	# there's nothing to opt into, so the old checkbox must be gone entirely
	assert 'id="feedback-include-identity"' not in html


def test_the_widget_is_absent_when_signed_out(anon):
	html = anon.get("/").get_data(as_text=True)
	assert 'id="feedback-form"' not in html


def test_body_exposes_only_role_and_display_name_not_any_other_pii(student):
	html = student.get("/").get_data(as_text=True)
	assert 'data-role="basic user"' in html
	assert 'data-user-name=' in html
	# nothing that looks like an email, employee id or password hash should ever land in a bare
	# data attribute on <body> -- those aren't needed by the widget and must not be exposed there
	body_tag = html.split("<body", 1)[1].split(">", 1)[0]
	assert "@" not in body_tag
	assert "password" not in body_tag.lower()


def test_widget_js_posts_to_the_support_endpoint_and_never_touches_github():
	source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
	assert "FEEDBACK_REPO" not in source
	assert "github.com" not in source
	handler = source.split("function wireFeedbackWidget")[1].split("\n  }\n\n  // ")[0]
	assert "HKC.fetchJSON('/api/support/quick-feedback'" in handler
	assert "window.open(" not in handler
	assert "feedback-include-identity" not in handler


def test_diagnostics_buffer_is_capped_and_query_strings_are_stripped_from_network_log():
	source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
	assert "MAX_DIAGNOSTICS = 25" in source
	assert "url.split('?')[0]" in source
