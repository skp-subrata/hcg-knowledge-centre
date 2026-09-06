"""Synchroniser-token CSRF protection for the session-authenticated web routes.

A random token is stored in the Flask session the first time a page is rendered
and exposed to templates as ``csrf_token()``.  Every state-changing request
(anything but GET/HEAD/OPTIONS/TRACE) must echo it back, either as the form
field ``csrf_token`` or the ``X-CSRF-Token`` header.  Requests that carry an
``X-API-Key`` header authenticate with API credentials rather than a cookie, so
they are exempt: a browser cannot attach that header cross-site.

``app.config["CSRF_ENABLED"]`` (env ``LMS_CSRF``, default on) turns the check
off for test clients that post forms without rendering pages first.
"""
import hmac
import secrets

from flask import flash, jsonify, redirect, request, session

SESSION_KEY = "_csrf_token"
FORM_FIELD = "csrf_token"
HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
REJECTION_MESSAGE = "Your form expired for security reasons. Please try again."


def generate_token():
	"""Return the session's CSRF token, creating it on first use."""
	token = session.get(SESSION_KEY)
	if not token:
		token = secrets.token_urlsafe(32)
		session[SESSION_KEY] = token
	return token


def is_exempt(req):
	"""Safe methods and API-key requests never need a token."""
	return req.method in SAFE_METHODS or "X-API-Key" in req.headers


def token_is_valid(req):
	expected = session.get(SESSION_KEY)
	supplied = req.headers.get(HEADER) or req.form.get(FORM_FIELD)
	return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def wants_json(req):
	return req.headers.get("X-Requested-With") == "XMLHttpRequest" or req.is_json or req.accept_mimetypes.best == "application/json"


def _same_origin_referrer(default_url):
	ref = request.referrer
	if ref and ref.startswith(request.host_url):
		return ref
	return default_url


def init_csrf(app):
	app.config.setdefault("CSRF_ENABLED", True)

	@app.before_request
	def _reject_requests_without_a_valid_token():
		if not app.config.get("CSRF_ENABLED") or is_exempt(request) or token_is_valid(request):
			return None
		if wants_json(request):
			return jsonify({"error": "Invalid or missing CSRF token. Reload the page and try again."}), 400
		flash(REJECTION_MESSAGE, "error")
		return redirect(_same_origin_referrer("/"))

	@app.context_processor
	def _expose_token():
		return {"csrf_token": generate_token}
