"""The floating 'send feedback' button: composes a prefilled GitHub issue client-side, no
server round-trip. Server-side, there's nothing to submit to -- these tests pin what the
button/sheet expose to JS (and, deliberately, what they must never expose)."""
from pathlib import Path

import app as app_module

ROOT = Path(app_module.__file__).resolve().parent


def test_the_widget_is_present_for_a_signed_in_user(student):
	html = student.get("/").get_data(as_text=True)
	assert 'data-dialog-open="feedback-sheet"' in html
	assert 'id="feedback-form"' in html
	assert 'id="feedback-title"' in html and 'id="feedback-details"' in html
	# opt-in only: identity is never included unless the person checks the box themselves
	assert 'id="feedback-include-identity"' in html
	assert 'checked' not in html.split('id="feedback-include-identity"')[1].split('>')[0]


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


def test_widget_js_targets_the_real_repo_and_never_calls_a_server_endpoint():
	source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
	assert "FEEDBACK_REPO = 'skp-subrata/hcg-knowledge-centre'" in source
	assert "github.com/${FEEDBACK_REPO}/issues/new" in source
	# the feedback submit handler must not fetch/POST anywhere -- it only opens a URL
	handler = source.split("function wireFeedbackWidget")[1].split("\n  }\n\n  // ")[0]
	assert "fetch(" not in handler and "HKC.fetchJSON(" not in handler


def test_diagnostics_buffer_is_capped_and_query_strings_are_stripped_from_network_log():
	source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
	assert "MAX_DIAGNOSTICS = 25" in source
	assert "url.split('?')[0]" in source
