"""Builders that put the seeded database into a richer, known state.

The seed has 107 users, two courses ("Python Foundations", "Design Essentials",
both created by subratakumar.pradhan and assigned to maya.student), one question
bank and a few assessments - but no posts, groups, attempts, API credentials or
uploads. ``build_world`` adds one of each so every route has something to hit.
Rows are inserted directly so the fixtures do not depend on the routes under test.
"""
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class World:
	users: dict = field(default_factory=dict)         # username -> id
	python_course_id: int = 0                          # published, created by subratakumar.pradhan, assigned to maya
	design_course_id: int = 0                          # published PDF course
	mod_draft_course_id: int = 0                       # draft owned by mod (deletable/publishable)
	mod_published_course_id: int = 0                   # published, owned by mod, assigned to student and maya
	certified_course_id: int = 0                       # == mod_published_course_id; maya is CERTIFIED on it
	pre_assessment_id: int = 0                         # 1-question 'pre' assessment on Python Foundations
	post_assessment_id: int = 0                        # multi-question 'post' assessment on Python Foundations
	attempt_id: int = 0                                # maya's passing attempt on post_assessment
	group_id: int = 0                                  # created by mod, mod is Active moderator, student is a member
	published_post_id: int = 0                         # by mod
	pending_post_id: int = 0                           # by student
	draft_post_id: int = 0                             # by student
	notification_id: int = 0                           # maya's seeded notification
	interest_id: int = 0                               # first interest_master row
	department_id: int = 0
	location_id: int = 0
	upload_name: str = "planted.pdf"
	api_keys: dict = field(default_factory=dict)      # username -> headers


def _connect(db_path):
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	connection.execute("PRAGMA foreign_keys = ON")
	return connection


def build_world(db_path, upload_folder):
	"""Populate *db_path* and return a World with every id a test needs."""
	world = World()
	connection = _connect(db_path)
	try:
		with connection:
			c = connection
			for row in c.execute("SELECT id, username FROM users"):
				world.users[row["username"]] = row["id"]
			u = world.users
			admin, mod, student, maya = u["admin"], u["mod"], u["student"], u["maya.student"]

			world.python_course_id = c.execute("SELECT id FROM courses WHERE name = 'Python Foundations'").fetchone()["id"]
			world.design_course_id = c.execute("SELECT id FROM courses WHERE name = 'Design Essentials'").fetchone()["id"]

			world.mod_draft_course_id = c.execute(
				"INSERT INTO courses (name, description, category, content_type, content_url, created_by, status) "
				"VALUES ('World Draft Course', 'draft for tests', 'Testing', 'URL', '#', ?, 'draft')", (mod,)
			).lastrowid
			world.mod_published_course_id = c.execute(
				"INSERT INTO courses (name, description, category, content_type, content_url, created_by, status) "
				"VALUES ('World Published Course', 'published for tests', 'Testing', 'URL', 'https://example.com/course', ?, 'published')", (mod,)
			).lastrowid
			world.certified_course_id = world.mod_published_course_id
			for sid in (student, maya):
				c.execute("INSERT OR IGNORE INTO course_assignments (course_id, student_id, status) VALUES (?, ?, 'in_progress')",
				          (world.mod_published_course_id, sid))

			# maya is certified on the mod's published course
			c.execute("UPDATE course_assignments SET status = 'certified' WHERE course_id = ? AND student_id = ?",
			          (world.mod_published_course_id, maya))
			c.execute(
				"INSERT INTO certificates (student_id, course_id, cert_uid) VALUES (?, ?, ?)",
				(maya, world.mod_published_course_id, f"CERT-{world.mod_published_course_id}-{maya}-world0001"),
			)
			c.execute(
				"INSERT OR IGNORE INTO course_certifications (user_id, course_id, user_name, course_name, assessment_score, pass_mark, "
				"assessment_attempts, badge, certification_status, certificate_id, feedback_rating, feedback_comments) "
				"VALUES (?, ?, 'Maya Student', 'World Published Course', 95, 60, 1, 'PLATINUM', 'CERTIFIED', ?, 9, 'great')",
				(maya, world.mod_published_course_id, f"CERT-{world.mod_published_course_id}-{maya}-world0001"),
			)

			pre = c.execute("SELECT id FROM assessments WHERE course_id = ? AND type = 'pre' ORDER BY id LIMIT 1", (world.python_course_id,)).fetchone()
			post = c.execute("SELECT id FROM assessments WHERE course_id = ? AND type = 'post' ORDER BY id LIMIT 1", (world.python_course_id,)).fetchone()
			world.pre_assessment_id = pre["id"] if pre else 0
			world.post_assessment_id = post["id"] if post else world.pre_assessment_id

			# maya has a passing attempt on the post assessment
			world.attempt_id = c.execute(
				"INSERT INTO assessment_attempts (assessment_id, student_id, attempt_no, score, percentage, status, result) "
				"VALUES (?, ?, 1, 5, 100.0, 'submitted', 'pass')", (world.post_assessment_id, maya)
			).lastrowid
			for q in c.execute("SELECT q.id, q.correct_option, q.marks FROM questions q JOIN assessment_questions aq ON aq.question_id = q.id WHERE aq.assessment_id = ?", (world.post_assessment_id,)):
				c.execute("INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) VALUES (?, ?, ?, 1, ?)",
				          (world.attempt_id, q["id"], q["correct_option"], q["marks"] or 1))

			# a group run by mod with student as member
			world.group_id = c.execute(
				"INSERT INTO groups (name, description, group_type, status, created_by) VALUES ('World Group', 'group for tests', 'team', 'active', ?)", (mod,)
			).lastrowid
			c.execute("INSERT OR IGNORE INTO group_moderators (group_id, user_id, status) VALUES (?, ?, 'Active')", (world.group_id, mod))
			c.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location) VALUES (?, ?, 'EMP-STUDENT', '', 'Operations', 'Hyderabad')",
			          (world.group_id, student))

			# community posts in three states
			def post(title, author, status):
				return c.execute(
					"INSERT INTO posts (title, description, content_type, category, created_by, status, version_number) "
					"VALUES (?, '<p>body</p>', 'Text/Article', 'General', ?, ?, 1)", (title, author, status)
				).lastrowid
			world.published_post_id = post("World Published Post", mod, "PUBLISHED")
			c.execute("UPDATE posts SET published_by = ?, published_at = CURRENT_TIMESTAMP WHERE id = ?", (mod, world.published_post_id))
			world.pending_post_id = post("World Pending Post", student, "PENDING_APPROVAL")
			world.draft_post_id = post("World Draft Post", student, "DRAFT")
			c.execute("INSERT INTO post_comments (post_id, user_id, comment_text) VALUES (?, ?, 'first comment')", (world.published_post_id, student))

			notif = c.execute("SELECT id FROM notifications WHERE user_id = ? ORDER BY id LIMIT 1", (maya,)).fetchone()
			world.notification_id = notif["id"] if notif else c.execute(
				"INSERT INTO notifications (user_id, message, type) VALUES (?, 'world notification', 'system')", (maya,)).lastrowid

			world.interest_id = c.execute("SELECT id FROM interest_master ORDER BY id LIMIT 1").fetchone()["id"]
			world.department_id = c.execute("SELECT department_id FROM departments ORDER BY department_id LIMIT 1").fetchone()["department_id"]
			world.location_id = c.execute("SELECT location_id FROM locations ORDER BY location_id LIMIT 1").fetchone()["location_id"]

			# a wallet with a balance for maya
			c.execute("INSERT OR IGNORE INTO user_wallets (user_id, current_balance, total_earned) VALUES (?, 500, 500)", (maya,))
			c.execute(
				"INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after) "
				"VALUES (?, 'COURSE_CERTIFICATION', 'world', 'certificate', 'world seed', 500, 'EARN', 0, 500)", (maya,)
			)

			# API credentials for the three roles
			for username in ("admin", "mod", "student"):
				c.execute("INSERT INTO api_credentials (user_id, api_key, api_secret, status) VALUES (?, ?, ?, 'active')",
				          (u[username], f"ak_world_{username}", f"as_world_{username}"))
				world.api_keys[username] = {"X-API-Key": f"ak_world_{username}", "X-API-Secret": f"as_world_{username}"}
	finally:
		connection.close()

	Path(upload_folder).mkdir(parents=True, exist_ok=True)
	(Path(upload_folder) / world.upload_name).write_bytes(b"%PDF-1.4 planted for tests\n")
	return world


# (rule, method) -> {persona: status}. Filled by tests/test_route_matrix.py and written
# to a markdown file by conftest's pytest_sessionfinish when --matrix-out is given.
MATRIX_RESULTS = {}


class FakeHTTPResponse:
	"""Stand-in for urllib's response object: enough for proxy_embed and detect_content_type."""

	def __init__(self, url, body=b"<html><body>fake</body></html>", content_type="text/html; charset=utf-8"):
		self._url = url
		self._body = body
		self.status = 200
		self.headers = {"Content-Type": content_type, "X-Frame-Options": "DENY"}

	def read(self, *args, **kwargs):
		return self._body

	def getcode(self):
		return self.status

	def geturl(self):
		return self._url

	def info(self):
		return self

	def get_content_type(self):
		return self.headers["Content-Type"].split(";")[0]

	def get(self, key, default=None):
		return self.headers.get(key, default)

	def items(self):
		return self.headers.items()

	def getheaders(self):
		return list(self.headers.items())

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		return False


def make_assessment(db_path, course_id, kind="post", pass_percentage=60, max_attempts=1, questions=(("Question 1", "a", 1),), creator_id=1, title=None):
	"""Create a question bank, its questions and an assessment on *course_id*.

	*questions* is a sequence of (text, correct_option, marks). Returns (assessment_id, [question_id, ...]).
	"""
	connection = _connect(db_path)
	try:
		with connection:
			title = title or f"{kind.title()} assessment {course_id}"
			bank_id = connection.execute(
				"INSERT INTO question_banks (name, category, created_by) VALUES (?, 'Testing', ?)", (f"{title} bank", creator_id)
			).lastrowid
			assessment_id = connection.execute(
				"INSERT INTO assessments (course_id, type, title, pass_percentage, max_attempts) VALUES (?, ?, ?, ?, ?)",
				(course_id, kind, title, pass_percentage, max_attempts),
			).lastrowid
			question_ids = []
			for text, correct, marks in questions:
				question_id = connection.execute(
					"INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, created_by) "
					"VALUES (?, ?, 'A', 'B', 'C', 'D', ?, ?, 'medium', ?)",
					(bank_id, text, correct, marks, creator_id),
				).lastrowid
				connection.execute("INSERT INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (assessment_id, question_id))
				question_ids.append(question_id)
	finally:
		connection.close()
	return assessment_id, question_ids


def assign(db_path, course_id, user_id, status="in_progress"):
	"""Give *user_id* an assignment on *course_id* (idempotent)."""
	connection = _connect(db_path)
	try:
		with connection:
			connection.execute(
				"INSERT INTO course_assignments (course_id, student_id, status) VALUES (?, ?, ?) "
				"ON CONFLICT(course_id, student_id) DO UPDATE SET status = excluded.status",
				(course_id, user_id, status),
			)
	finally:
		connection.close()
