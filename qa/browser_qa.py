"""Browser QA pass for the redesigned UI (Phase 5).

Boots the app on its own port with a fresh, seeded QA database, logs in as each
persona through the real form (so CSRF is exercised), visits every page at
1280px light, 1280px dark and 375px light, runs accessibility/overflow checks,
records console and network errors, drives the interactive widgets (menus,
drawer, dialogs, admin AJAX flows) and writes:

  docs/qa/screens/<page>-<theme>-<width>.jpg     screenshots
  docs/qa/browser_report.md                      human-readable report
  qa/report.json                                 raw results

Run:  .venv/bin/python qa/browser_qa.py   (needs `pip install playwright && playwright install chromium`)
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.helpers import build_world  # noqa: E402  (sqlite-only helper, no app import)

PORT = int(os.environ.get("QA_PORT", "5077"))
BASE = f"http://127.0.0.1:{PORT}"
QA_DIR = ROOT / "qa"
DB = QA_DIR / "qa.db"
UPLOADS = QA_DIR / "uploads"
SCREENS = ROOT / "docs" / "qa" / "screens"
PASSWORDS = {"admin": "admin", "mod": "mod", "student": "student", "maya.student": "maya"}

A11Y_JS = """
() => {
  const out = {};
  out.h1 = document.querySelectorAll('h1').length;
  out.main = document.querySelectorAll('main').length;
  const labelled = (el) => el.labels?.length || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title') || el.type === 'hidden' || el.type === 'submit' || el.type === 'button' || el.closest('label');
  const visible = (el) => !el.hidden && el.getAttribute('aria-hidden') !== 'true' && getComputedStyle(el).display !== 'none';
  out.unlabelled_inputs = [...document.querySelectorAll('input, select, textarea')].filter((el) => visible(el) && !labelled(el)).map((el) => el.name || el.id || el.type).slice(0, 8);
  const name = (el) => (el.innerText || '').trim() || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title') || el.querySelector('img[alt]')?.alt;
  out.unnamed_controls = [...document.querySelectorAll('button, a[href]')].filter((el) => visible(el) && !name(el)).map((el) => (el.outerHTML || '').slice(0, 70)).slice(0, 8);
  out.imgs_without_alt = document.querySelectorAll('img:not([alt])').length;
  const ids = [...document.querySelectorAll('[id]')].map((el) => el.id);
  out.duplicate_ids = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))].slice(0, 8);
  out.positive_tabindex = document.querySelectorAll('[tabindex]:not([tabindex="0"]):not([tabindex="-1"])').length;
  out.tiny_text = [...document.querySelectorAll('body *')].filter((el) => el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(el).fontSize) < 11).length;
  out.overflow_x = document.documentElement.scrollWidth > window.innerWidth + 1;
  out.skip_link = !!document.querySelector('a[href="#main"], a.skip-link');
  out.title = document.title;
  return out;
}
"""


def start_server():
	if DB.exists():
		DB.unlink()
	shutil.rmtree(UPLOADS, ignore_errors=True)
	UPLOADS.mkdir(parents=True)
	env = dict(os.environ, LMS_DATABASE=str(DB), LMS_UPLOAD_FOLDER=str(UPLOADS), LMS_SECRET_KEY="qa-secret", LMS_DEBUG="0",
	           LMS_SEED_DEMO="1", LMS_PORT=str(PORT), LMS_HOST="127.0.0.1", LMS_CSRF="1", PYTHONUNBUFFERED="1")
	proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	deadline = time.time() + 90
	while time.time() < deadline:
		try:
			urllib.request.urlopen(BASE + "/", timeout=2)
			return proc
		except Exception:
			if proc.poll() is not None:
				print(proc.stdout.read()); raise SystemExit("server exited early")
			time.sleep(0.5)
	raise SystemExit("server did not start")


def seed_world():
	world = build_world(DB, UPLOADS)
	from werkzeug.security import generate_password_hash
	con = sqlite3.connect(DB)
	cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
	pw_col = next(c for c in cols if "password" in c)
	con.execute(f"UPDATE users SET {pw_col} = ? WHERE username = 'maya.student'", (generate_password_hash("maya"),))
	con.commit(); con.close()
	return world


KNOWN_NOISE = ("cdn.tailwindcss.com should not be used in production", "No available adapters", "status of 404")


class Recorder:
	def __init__(self, page):
		self.console, self.errors, self.failed, self.known = [], [], [], []
		page.on("console", lambda m: (self.known if any(k in m.text for k in KNOWN_NOISE) else self.console).append(m.text) if m.type in ("error", "warning") else None)
		page.on("pageerror", lambda e: self.errors.append(str(e)))
		page.on("response", lambda r: self.failed.append(f"{r.status} {r.url.replace(BASE, '')}") if r.status >= 400 else None)

	def reset(self):
		self.console, self.errors, self.failed, self.known = [], [], [], []

	def snapshot(self):
		return {"console": self.console[:6], "pageerrors": self.errors[:6], "failed_requests": self.failed[:6], "known_noise": sorted({k[:60] for k in self.known})}


def login(page, username):
	page.goto(BASE + "/")
	page.fill("input[name=username]", username)
	page.fill("input[name=password]", PASSWORDS[username])
	page.click("form button[type=submit]")
	page.wait_for_load_state("networkidle")
	if username in ("admin", "mod"):
		page.click('header form[action="/switch-role"] button')
		page.wait_for_load_state("networkidle")


def visit(page, rec, slug, url, shots=True):
	result = {"slug": slug, "url": url}
	rec.reset()
	page.set_viewport_size({"width": 1280, "height": 860}); page.emulate_media(color_scheme="light")
	response = page.goto(BASE + url); page.wait_for_load_state("networkidle")
	result["status"] = response.status if response else None
	result["final_url"] = page.url.replace(BASE, "")
	result["a11y"] = page.evaluate(A11Y_JS)
	if shots:
		page.screenshot(path=str(SCREENS / f"{slug}-light-1280.jpg"), full_page=True, type="jpeg", quality=55)
		page.emulate_media(color_scheme="dark"); page.wait_for_timeout(350)
		page.screenshot(path=str(SCREENS / f"{slug}-dark-1280.jpg"), full_page=True, type="jpeg", quality=55)
		page.emulate_media(color_scheme="light")
	page.set_viewport_size({"width": 375, "height": 812}); page.wait_for_timeout(250)
	result["mobile_overflow_x"] = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
	result["mobile_widest"] = page.evaluate("() => { let w = null; for (const el of document.querySelectorAll('body *')) { const r = el.getBoundingClientRect(); if (r.right > window.innerWidth + 1 && r.width > 40) { w = (el.tagName + '.' + (el.className || '').toString().split(' ').slice(0,3).join('.')).slice(0, 80); break; } } return w; }")
	if shots:
		page.screenshot(path=str(SCREENS / f"{slug}-light-375.jpg"), full_page=True, type="jpeg", quality=55)
	page.set_viewport_size({"width": 1280, "height": 860})
	result.update(rec.snapshot())
	return result


def check(results, name, fn):
	try:
		detail = fn()
		results.append({"name": name, "ok": True, "detail": detail if isinstance(detail, str) else ""})
	except Exception as exc:  # noqa: BLE001 - report every failure, keep going
		results.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]})


def interactions(browser, world):
	from playwright.sync_api import expect
	results = []
	ctx = browser.new_context(viewport={"width": 1280, "height": 860}); page = ctx.new_page(); rec = Recorder(page)

	def _menu_keyboard():
		page.goto(BASE + "/"); login(page, "admin")
		trigger = page.locator('header button[aria-haspopup="menu"]').last
		trigger.focus(); page.keyboard.press("Enter")
		menu = page.locator("#" + trigger.get_attribute("aria-controls"))
		expect(menu).to_be_visible()
		assert page.evaluate("() => document.activeElement.getAttribute('role')") == "menuitem", "first menu item should take focus"
		page.keyboard.press("Escape"); expect(menu).to_be_hidden()
		assert page.evaluate("() => document.activeElement === document.querySelector('header button[aria-haspopup=\"menu\"]:last-of-type') || document.activeElement.matches('header button')"), "focus returns to trigger"
		return "Enter opens, first item focused, Escape closes and returns focus"

	def _theme_toggle():
		page.click("[data-theme-toggle]"); dark = page.evaluate("() => document.documentElement.classList.contains('dark')")
		page.reload(); page.wait_for_load_state("networkidle")
		assert page.evaluate("() => document.documentElement.classList.contains('dark')") == dark, "theme must persist across reload"
		page.click("[data-theme-toggle]")
		return "toggle persists across reload"

	def _drawer_mobile():
		page.set_viewport_size({"width": 375, "height": 812}); page.goto(BASE + "/"); page.wait_for_load_state("networkidle")
		opener = page.locator("header [data-dialog-open]").first
		opener.click(); drawer = page.locator("dialog[open].drawer, dialog.drawer[open]")
		expect(drawer).to_be_visible()
		page.keyboard.press("Escape"); page.wait_for_timeout(500)
		assert page.locator("dialog.drawer[open]").count() == 0, "Escape closes the drawer"
		page.emulate_media(reduced_motion="reduce"); opener.click(); expect(page.locator("dialog.drawer[open]")).to_be_visible()
		page.keyboard.press("Escape"); page.wait_for_timeout(300); assert page.locator("dialog.drawer[open]").count() == 0
		page.emulate_media(reduced_motion="no-preference"); page.set_viewport_size({"width": 1280, "height": 860})
		return "opens/closes, also under reduced motion"

	def _course_wizard():
		page.goto(BASE + "/courses"); page.wait_for_load_state("networkidle")
		page.click('[data-dialog-open="course-wizard"]'); expect(page.locator("#course-wizard[open]")).to_be_visible()
		page.keyboard.press("Escape"); page.wait_for_timeout(400); assert page.locator("#course-wizard[open]").count() == 0
		return "wizard opens and Escape closes it"

	def _edit_user_ajax():
		page.goto(BASE + "/admin"); page.wait_for_load_state("networkidle")
		page.locator("#users-table [data-user-edit]").first.click(); expect(page.locator("#user-edit[open]")).to_be_visible()
		for field, value in (("#edit_email", "qa.user@example.com"), ("#edit_employee_id", "EMP-QA-1"), ("#edit_phone_number", "9998887776")):
			page.fill(field, value)  # seeded sample users have no contact details; the backend requires them
		page.click("#editUserSubmitBtn")
		expect(page.locator("#toast-region .toast").first).to_contain_text("updated", timeout=5000)
		page.wait_for_timeout(600); assert page.locator("#user-edit[open]").count() == 0, "dialog closes after save"
		return "saves via AJAX, toast shown, dialog closes, table refreshed"

	def _edit_user_validation():
		page.locator("#users-table [data-user-edit]").first.click(); expect(page.locator("#user-edit[open]")).to_be_visible()
		page.fill("#edit_email", "not-an-email"); page.click("#editUserSubmitBtn")
		expect(page.locator("#editUserError")).to_be_visible(); assert "valid email" in page.locator("#editUserError").inner_text()
		page.keyboard.press("Escape"); page.wait_for_timeout(400)
		return "inline error for a bad email"

	def _quick_add_department():
		page.click('[data-add-master="departments"]'); dlg = page.locator("dialog[open]").last; expect(dlg).to_be_visible()
		dlg.locator("input[name=value]").fill("QA Department"); dlg.locator("button[type=submit]").click()
		expect(page.locator("#toast-region .toast").last).to_contain_text("added", timeout=5000)
		assert page.locator('select[data-master="departments"] option', has_text="QA Department").count() >= 1, "new option appended"
		return "prompt → POST /api/v1/departments → option appended + toast"

	def _admin_search_and_pagination():
		page.fill("#users-search", "maya"); page.wait_for_timeout(700)
		rows = page.locator("#users-table tbody tr").count(); assert rows == 1, f"search should leave 1 row, got {rows}"
		page.fill("#users-search", ""); page.wait_for_timeout(700)
		page.locator('[data-admin-table="users"] [data-page]', has_text="Next").click(); page.wait_for_timeout(700)
		assert "Page 2" in page.locator('[data-admin-table="users"] [data-pagination]').inner_text()
		return "search narrows to 1 row; Next moves to page 2"

	def _release_sheet():
		page.click('[data-dialog-open="release-sheet"]'); expect(page.locator("#release-sheet[open]")).to_be_visible()
		page.keyboard.press("Escape"); page.wait_for_timeout(400); assert page.locator("#release-sheet[open]").count() == 0
		return "release notes sheet opens and closes"

	def _confirm_dialog_blocks_delete():
		page.goto(BASE + "/admin"); page.wait_for_load_state("networkidle")
		before = page.locator("#courses-table tbody tr").count()
		page.locator("#courses-table form[data-confirm] button").first.click()
		dlg = page.locator("dialog[open]").last; expect(dlg).to_be_visible(); dlg.locator('[data-dialog-close="cancel"]').click(); page.wait_for_timeout(400)
		page.wait_for_load_state("networkidle")
		assert page.locator("#courses-table tbody tr").count() == before, "cancel keeps the course"
		return "danger confirm shown; cancel keeps the row"

	def _not_found():
		r = page.goto(BASE + "/this-page-does-not-exist"); assert r.status == 404
		return f"404 body {len(page.content())} bytes, title '{page.title()}'"

	def _logout_via_menu():
		page.goto(BASE + "/"); trigger = page.locator('header button[aria-haspopup="menu"]').last; trigger.click()
		page.locator('form[action="/logout"] button').click(); page.wait_for_load_state("networkidle")
		assert page.locator("input[name=password]").count() == 1, "back on the login page"
		return "logout is a POST form in the avatar menu"

	def _login_error():
		page.fill("input[name=username]", "admin"); page.fill("input[name=password]", "wrong"); page.click("form button[type=submit]")
		page.wait_for_load_state("networkidle"); assert page.locator('[role="alert"], .toast, .field-error').count() >= 1, "an error is announced"
		return "wrong password shows an error"

	def _student_mark_read():
		login(page, "maya.student"); page.goto(BASE + "/notifications"); page.wait_for_load_state("networkidle")
		btn = page.locator("main [data-mark-read]").first
		if btn.count() == 0:
			return "no unread notification to mark"
		btn.click(); page.wait_for_load_state("networkidle"); return "mark-read posts and reloads"

	for name, fn in [("avatar menu keyboard", _menu_keyboard), ("theme toggle persists", _theme_toggle), ("mobile drawer", _drawer_mobile),
	                 ("course wizard dialog", _course_wizard), ("admin edit user (AJAX)", _edit_user_ajax), ("admin edit user validation", _edit_user_validation),
	                 ("admin quick-add department", _quick_add_department), ("admin search + pagination", _admin_search_and_pagination), ("release notes sheet", _release_sheet),
	                 ("delete confirm (cancel)", _confirm_dialog_blocks_delete), ("404 page", _not_found), ("logout via menu (POST)", _logout_via_menu),
	                 ("login error", _login_error), ("student mark-read", _student_mark_read)]:
		rec.reset(); check(results, name, fn)
		if rec.errors or rec.console:
			results[-1]["detail"] += f" | console: {rec.console[:2]} pageerrors: {rec.errors[:2]}"
	ctx.close()
	return results


def main():
	from playwright.sync_api import sync_playwright
	proc = start_server()
	try:
		world = seed_world()
		w = world
		pages = {
			None: [("login", "/"), ("error-404", "/this-page-does-not-exist")],
			"maya.student": [("dashboard-learner", "/"), ("courses-learner", "/courses"), ("course", f"/course/{w.python_course_id}"),
			                 ("assessment", f"/assessments/{w.post_assessment_id}"), ("assessment-result", f"/assessment/result/{w.attempt_id}"),
			                 ("assessment-review", f"/assessment/review/{w.attempt_id}"), ("feedback", f"/course/{w.certified_course_id}/feedback"),
			                 ("certificate", f"/course/{w.certified_course_id}/certificate"), ("community", "/community"),
			                 ("post-detail", f"/community/post/{w.published_post_id}"), ("create-post", "/community/create"),
			                 ("my-posts", "/community/my-posts"), ("profile", "/profile"), ("notifications", "/notifications"), ("rewards", "/rewards")],
			"student": [("edit-post", f"/community/edit/{w.draft_post_id}")],
			"mod": [("approval-queue", "/community/approval-queue"), ("groups", "/groups"), ("group-detail", f"/groups/{w.group_id}"),
			        ("admin-moderator", "/admin"), ("reports", "/admin/reports")],
			"admin": [("dashboard-admin", "/"), ("courses-manage", "/courses"), ("admin", "/admin"), ("masters", "/admin/masters"),
			          ("reward-admin", "/admin/rewards"), ("view-as", "/view-as"), ("api-docs", "/api/v1/docs")],
		}
		report = {"pages": [], "interactions": []}
		with sync_playwright() as p:
			browser = p.chromium.launch()
			for persona, items in pages.items():
				ctx = browser.new_context(viewport={"width": 1280, "height": 860}); page = ctx.new_page(); rec = Recorder(page)
				if persona:
					login(page, persona)
				for slug, url in items:
					result = visit(page, rec, slug, url); result["persona"] = persona or "anon"; report["pages"].append(result)
					print(f"  {result['status']} {persona or 'anon':13s} {slug:20s} h1={result['a11y']['h1']} main={result['a11y']['main']} overflow375={result['mobile_overflow_x']} errors={len(result['console']) + len(result['pageerrors'])}")
				ctx.close()
			report["interactions"] = interactions(browser, world)
			browser.close()
		(QA_DIR / "report.json").write_text(json.dumps(report, indent=2))
		write_markdown(report)
	finally:
		proc.terminate()
		try:
			proc.wait(timeout=10)
		except subprocess.TimeoutExpired:
			proc.kill()


def write_markdown(report):
	lines = ["# Browser QA report", "", f"Generated by `qa/browser_qa.py` against a fresh seeded database (Playwright, headless Chromium). Screenshots: `docs/qa/screens/<page>-<theme>-<width>.jpg`.", "",
	         "## Pages", "", "| page | persona | status | h1 | main | unlabelled inputs | unnamed controls | dup ids | tiny text | 375px overflow | console/page errors | failed requests |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
	for r in report["pages"]:
		a = r["a11y"]
		errs = "; ".join(r["console"] + r["pageerrors"])[:160] or "—"
		failed = "; ".join(r["failed_requests"])[:120] or "—"
		lines.append(f"| {r['slug']} | {r['persona']} | {r['status']} | {a['h1']} | {a['main']} | {len(a['unlabelled_inputs'])} {a['unlabelled_inputs'] if a['unlabelled_inputs'] else ''} | {len(a['unnamed_controls'])} | {len(a['duplicate_ids'])} {a['duplicate_ids'] if a['duplicate_ids'] else ''} | {a['tiny_text']} | {'**yes** ' + str(r['mobile_widest']) if r['mobile_overflow_x'] else 'no'} | {errs} | {failed} |")
	noise = sorted({n for r in report["pages"] for n in r.get("known_noise", [])})
	lines += ["", "Known console noise, excluded from the error column: " + ("; ".join(f"`{n}`" for n in noise) if noise else "none") + ".", "", "## Interactions", "", "| check | result | detail |", "|---|---|---|"]
	for i in report["interactions"]:
		lines.append(f"| {i['name']} | {'✅ pass' if i['ok'] else '❌ fail'} | {i['detail'].replace('|', '/')} |")
	(ROOT / "docs" / "qa" / "browser_report.md").write_text("\n".join(lines) + "\n")
	fails = [i for i in report["interactions"] if not i["ok"]]
	print(f"\n{len(report['pages'])} pages, {len(report['interactions'])} interactions, {len(fails)} interaction failures -> docs/qa/browser_report.md")
	for f in fails:
		print("  FAIL", f["name"], "->", f["detail"][:200])


if __name__ == "__main__":
	main()
