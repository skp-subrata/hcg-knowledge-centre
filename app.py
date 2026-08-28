import sqlite3
import os
import csv
from io import BytesIO
from io import StringIO, TextIOWrapper
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import parse_qs
from werkzeug.security import check_password_hash, generate_password_hash
from flask import Flask, flash, redirect, render_template, request, send_file, send_from_directory, session, url_for
from openpyxl import Workbook, load_workbook
from storage import save_file


DATABASE = Path(os.getenv("LMS_DATABASE", Path(__file__).with_name("users.db")))
UPLOAD_FOLDER = Path(os.getenv("LMS_UPLOAD_FOLDER", Path(__file__).with_name("uploads")))
ROLES = ("admin", "moderator", "basic user")

CONTENT_TYPES = ("URL", "PDF", "Video", "PPT")
QUESTION_COLUMNS = ("course_id", "course_name", "assessment_title", "assessment_type", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_option", "marks", "difficulty", "topic_tag")


def get_db():
	"""Open a row-producing SQLite connection with foreign keys enabled."""
	DATABASE.parent.mkdir(parents=True, exist_ok=True)
	connection = sqlite3.connect(DATABASE)
	connection.row_factory = sqlite3.Row
	connection.execute("PRAGMA foreign_keys = ON")
	return connection


def init_db():
	"""Create the LMS schema and seed the first administrator."""
	with get_db() as connection:
		# ── Core tables ──────────────────────────────────────────────────────────
		connection.execute("""
			CREATE TABLE IF NOT EXISTS users (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				full_name TEXT NOT NULL,
				username TEXT UNIQUE NOT NULL,
				password_hash TEXT NOT NULL,
				role TEXT NOT NULL CHECK (role IN ('admin', 'moderator', 'basic user'))
			)
		""")
		connection.execute(
			"INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)",
			("Subratakumar Pradhan", "subratakumar.pradhan", generate_password_hash("admin123"), "admin"),
		)
		connection.execute("""
			CREATE TABLE IF NOT EXISTS courses (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				content_type TEXT NOT NULL CHECK (content_type IN ('URL', 'PDF', 'Video', 'PPT')),
				content_url TEXT NOT NULL,
				created_by INTEGER NOT NULL REFERENCES users(id),
				description TEXT DEFAULT '',
				category TEXT DEFAULT 'General',
				status TEXT DEFAULT 'published'
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS course_assignments (
				course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
				student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				status TEXT DEFAULT 'not_started',
				completed_at TEXT,
				PRIMARY KEY (course_id, student_id)
			)
		""")
		connection.execute("CREATE INDEX IF NOT EXISTS idx_assignments_student ON course_assignments(student_id)")
		connection.execute("CREATE INDEX IF NOT EXISTS idx_courses_creator ON courses(created_by)")

		# ── Migrate courses table if old schema (missing PPT or extra columns) ──
		table_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'courses'").fetchone()[0]
		if "'PPT'" not in table_sql:
			connection.execute("ALTER TABLE courses RENAME TO courses_legacy")
			connection.execute("CREATE TABLE courses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, content_type TEXT NOT NULL CHECK (content_type IN ('URL', 'PDF', 'Video', 'PPT')), content_url TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), description TEXT DEFAULT '', category TEXT DEFAULT 'General', status TEXT DEFAULT 'published')")
			connection.execute("INSERT INTO courses (id, name, content_type, content_url, created_by) SELECT id, name, content_type, content_url, created_by FROM courses_legacy")
			connection.execute("DROP TABLE courses_legacy")

		# ── Migrate course_assignments: add status/completed_at if missing ──────
		assignment_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'course_assignments'").fetchone()
		if assignment_sql:
			assignment_sql = assignment_sql[0]
			if "courses_legacy" in assignment_sql:
				
				connection.execute("PRAGMA foreign_keys = OFF")
				connection.execute("ALTER TABLE course_assignments RENAME TO assignments_legacy")
				connection.execute("CREATE TABLE course_assignments (course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, status TEXT DEFAULT 'not_started', completed_at TEXT, PRIMARY KEY (course_id, student_id))")
				connection.execute("INSERT INTO course_assignments (course_id, student_id) SELECT course_id, student_id FROM assignments_legacy")
				connection.execute("DROP TABLE assignments_legacy")
				connection.execute("PRAGMA foreign_keys = ON")
			elif "status" not in assignment_sql:
				connection.execute("ALTER TABLE course_assignments ADD COLUMN status TEXT DEFAULT 'not_started'")
				connection.execute("ALTER TABLE course_assignments ADD COLUMN completed_at TEXT")

		# ── Remaining tables (assessments, questions, etc.) ───────────────────
		connection.executescript("""
			CREATE TABLE IF NOT EXISTS question_banks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT DEFAULT 'General', created_by INTEGER NOT NULL REFERENCES users(id));
			CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, question_bank_id INTEGER NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE, question_text TEXT NOT NULL, option_a TEXT NOT NULL, option_b TEXT NOT NULL, option_c TEXT NOT NULL, option_d TEXT NOT NULL, correct_option TEXT NOT NULL, marks INTEGER DEFAULT 1, difficulty TEXT DEFAULT 'medium', topic_tag TEXT DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id));
			CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, type TEXT NOT NULL, title TEXT NOT NULL, pass_percentage INTEGER DEFAULT 60, max_attempts INTEGER DEFAULT 1);
			CREATE TABLE IF NOT EXISTS assessment_questions (assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE, PRIMARY KEY(assessment_id, question_id));
			CREATE TABLE IF NOT EXISTS assessment_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, attempt_no INTEGER DEFAULT 1, score INTEGER DEFAULT 0, percentage REAL DEFAULT 0, status TEXT DEFAULT 'in_progress', result TEXT DEFAULT 'fail', started_at TEXT DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT);
			CREATE TABLE IF NOT EXISTS attempt_answers (id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id), selected_option TEXT, is_correct INTEGER DEFAULT 0, marks_awarded INTEGER DEFAULT 0, UNIQUE(attempt_id, question_id));
			CREATE TABLE IF NOT EXISTS certificates (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES users(id), course_id INTEGER NOT NULL REFERENCES courses(id), cert_uid TEXT UNIQUE NOT NULL, issued_date TEXT DEFAULT CURRENT_DATE, file_url TEXT);
			CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, type TEXT DEFAULT 'system', is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
			CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
			CREATE INDEX IF NOT EXISTS idx_questions_bank ON questions(question_bank_id);
			CREATE INDEX IF NOT EXISTS idx_attempt_student ON assessment_attempts(student_id);
		""")
		seed_demo_data(connection)


def seed_demo_data(connection):
	"""Insert a small, repeatable dataset for local exploration."""
	for name, username, role in (("Aarav Moderator", "aarav.moderator", "moderator"), ("Maya Student", "maya.student", "basic user"), ("Rohan Student", "rohan.student", "basic user")):
		
		# Migrate users table for profile fields
		table_info = connection.execute("PRAGMA table_info(users)").fetchall()
		columns = [col['name'] for col in table_info]
		if 'email' not in columns:
			connection.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN phone_number TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT DEFAULT ''")

		
		# Migrate courses table for new fields
		courses_info = connection.execute("PRAGMA table_info(courses)").fetchall()
		course_cols = [col['name'] for col in courses_info]
		if 'tags' not in course_cols:
			connection.execute("ALTER TABLE courses ADD COLUMN tags TEXT DEFAULT ''")
		if 'duration_minutes' not in course_cols:
			connection.execute("ALTER TABLE courses ADD COLUMN duration_minutes INTEGER DEFAULT 0")
		if 'difficulty' not in course_cols:
			connection.execute("ALTER TABLE courses ADD COLUMN difficulty TEXT DEFAULT 'beginner'")
		if 'thumbnail_color' not in course_cols:
			connection.execute("ALTER TABLE courses ADD COLUMN thumbnail_color TEXT DEFAULT '#6366f1'")

		connection.execute("INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)", (name, username, generate_password_hash("learn123"), role))
	admin = connection.execute("SELECT id FROM users WHERE username = 'subratakumar.pradhan'").fetchone()[0]
	student = connection.execute("SELECT id FROM users WHERE username = 'maya.student'").fetchone()[0]
	course_row = connection.execute("SELECT id FROM courses WHERE name = 'Python Foundations'").fetchone()
	if course_row:
		course_id = course_row[0]
	else:
		course_id = connection.execute("INSERT INTO courses (name, description, category, content_type, content_url, created_by) VALUES ('Python Foundations', 'Learn practical Python from the ground up.', 'Programming', 'Video', 'https://www.youtube.com/watch?v=rfscVS0vtbw', ?)", (admin,)).lastrowid

	connection.execute("INSERT OR IGNORE INTO course_assignments (course_id, student_id) VALUES (?, ?)", (course_id, student))
	second = connection.execute("SELECT id FROM courses WHERE name = 'Design Essentials'").fetchone()
	if not second:
		second = (connection.execute("INSERT INTO courses (name, description, category, content_type, content_url, created_by) VALUES ('Design Essentials', 'Build clear and useful interfaces.', 'Design', 'PDF', 'https://www.w3.org/WAI/fundamentals/accessibility-intro/', ?)", (admin,)).lastrowid,)
	connection.execute("INSERT OR IGNORE INTO course_assignments (course_id, student_id) VALUES (?, ?)", (second[0], student))
	bank = connection.execute("SELECT id FROM question_banks WHERE name = 'Python Basics Quiz'").fetchone()
	if not bank:
		bank = (connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES ('Python Basics Quiz', 'Programming', ?)", (admin,)).lastrowid,)
	question = connection.execute("SELECT id FROM questions WHERE question_bank_id = ? LIMIT 1", (bank[0],)).fetchone()
	if not question:
		question = (connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, created_by) VALUES (?, 'Which keyword defines a function in Python?', 'func', 'def', 'function', 'lambda', 'b', ?)", (bank[0], admin)).lastrowid,)
	assessment = connection.execute("SELECT id FROM assessments WHERE course_id = ? AND title = 'Python readiness check'", (course_id,)).fetchone()
	if not assessment:
		assessment = (connection.execute("INSERT INTO assessments (course_id, type, title, pass_percentage) VALUES (?, 'pre', 'Python readiness check', 60)", (course_id,)).lastrowid,)
	connection.execute("INSERT OR IGNORE INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (assessment[0], question[0]))
	connection.execute("INSERT OR IGNORE INTO notifications (user_id, message, type) VALUES (?, 'Python Foundations is ready for you.', 'assignment')", (student,))
	seed_course_questions(connection, admin)


def seed_course_questions(connection, creator_id):
	"""Ensure every course has five linked sample MCQs."""
	question_sets = {
		"ai": [
			("What does AI stand for?", "Automated Internet", "Artificial Intelligence", "Applied Information", "Advanced Integration", "b"),
			("Which field helps computers understand human language?", "NLP", "Networking", "Graphics", "Compilers", "a"),
			("What is training data used for?", "Teaching a model patterns", "Cooling a server", "Designing hardware", "Encrypting files", "a"),
			("Which is an example of supervised learning?", "Clustering", "Classification with labels", "Random search", "Compression", "b"),
			("What does a model prediction represent?", "A learned estimate", "A database backup", "A file format", "A network cable", "a"),
		],
		"python foundations": [
			("Which collection stores key-value pairs?", "List", "Tuple", "Dictionary", "Set", "c"),
			("Which keyword starts a loop over items?", "for", "case", "loop", "each", "a"),
			("What type is returned by input()?", "int", "str", "bool", "list", "b"),
			("Which symbol begins a Python comment?", "//", "#", "--", "/*", "b"),
			("What does len() return?", "The item count", "The data type", "The last item", "A sorted copy", "a"),
		],
		"design essentials": [
			("What improves text readability most?", "Low contrast", "Clear hierarchy", "Tiny type", "Crowded spacing", "b"),
			("What does responsive design adapt to?", "Screen size", "Database size", "File names", "CPU brand", "a"),
			("A user flow describes what?", "User steps through a task", "Color values", "Server logs", "Image pixels", "a"),
			("What is whitespace in a layout?", "Unused visual space", "Broken HTML", "Hidden text", "A font style", "a"),
			("What should a primary button communicate?", "The main action", "Every possible action", "A warning only", "Navigation history", "a"),
		],
		"test 1": [
			("What is the first step in a good test?", "Define expected behavior", "Skip requirements", "Delete data", "Deploy immediately", "a"),
			("What does a pass result mean?", "Expected behavior was observed", "The test was skipped", "The app crashed", "No assertion ran", "a"),
			("Why use test cases?", "To verify repeatable scenarios", "To replace documentation", "To slow releases", "To hide defects", "a"),
			("What is a regression test for?", "Checking old behavior after changes", "Choosing colors", "Creating passwords", "Compressing videos", "a"),
			("What should an assertion compare?", "Actual and expected values", "Two usernames only", "File sizes only", "Random outputs", "a"),
		],
	}
	for course in connection.execute("SELECT id, name FROM courses").fetchall():
		key = course["name"].lower()
		questions = question_sets.get(key, question_sets["test 1"])
		bank_name = f"{course['name']} Sample Questions"
		bank = connection.execute("SELECT id FROM question_banks WHERE name = ?", (bank_name,)).fetchone()
		if not bank:
			bank = (connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, 'Sample', ?)", (bank_name, creator_id)).lastrowid,)
		assessment = connection.execute("SELECT id FROM assessments WHERE course_id = ? ORDER BY id LIMIT 1", (course["id"],)).fetchone()
		if not assessment:
			assessment = (connection.execute("INSERT INTO assessments (course_id, type, title, pass_percentage) VALUES (?, 'post', ?, 60)", (course["id"], f"{course['name']} assessment")).lastrowid,)
		for text, option_a, option_b, option_c, option_d, correct in questions:
			question = connection.execute("SELECT id FROM questions WHERE question_bank_id = ? AND question_text = ?", (bank[0], text)).fetchone()
			if not question:
				question = (connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (bank[0], text, option_a, option_b, option_c, option_d, correct, creator_id)).lastrowid,)
			connection.execute("INSERT OR IGNORE INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (assessment[0], question[0]))


def staff_required(view):
	"""Allow only administrators and moderators into the staff workspace."""
	@wraps(view)
	def wrapped(*args, **kwargs):
		if session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
		return view(*args, **kwargs)
	return wrapped


def admin_required(view):
	"""Allow only a non-impersonating administrator."""
	@wraps(view)
	def wrapped(*args, **kwargs):
		if session.get("role") != "admin" or session.get("impersonator_id"):
			return redirect(url_for("home"))
		return view(*args, **kwargs)
	return wrapped


def content_location(field_name):
	"""Return an uploaded file URL or a validated external content URL."""
	upload = request.files.get(field_name)
	if upload and upload.filename:
		return "/uploads/" + save_file(upload, str(UPLOAD_FOLDER))
	content_url = request.form.get("content_url", "").strip()
	if urlparse(content_url).scheme in ("http", "https"):
		return content_url
	return None


def embed_url(value):
	"""Convert supported video links into iframe-friendly URLs."""
	parsed = urlparse(value or "")
	if parsed.netloc in ("youtube.com", "www.youtube.com", "m.youtube.com"):
		video_id = parse_qs(parsed.query).get("v", [""])[0]
		return f"https://www.youtube.com/embed/{video_id}" if video_id else value
	if parsed.netloc == "youtu.be":
		return f"https://www.youtube.com/embed/{parsed.path.strip('/')}"
	return value


def course_is_visible(connection, course_id, user_id):
	"""Return whether a user is assigned to or created a course."""
	return connection.execute("SELECT 1 FROM courses c LEFT JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE c.id = ? AND (c.created_by = ? OR ca.student_id IS NOT NULL)", (user_id, course_id, user_id)).fetchone() is not None


def course_is_manageable(connection, course_id, user_id, role):
	"""Return whether a staff user may manage a course."""
	return role == "admin" or connection.execute("SELECT 1 FROM courses WHERE id = ? AND created_by = ?", (course_id, user_id)).fetchone() is not None


def question_template():
	"""Build a blank Excel template for course assessment questions."""
	workbook = Workbook()
	workbook.active.append(QUESTION_COLUMNS)
	# Pre-fill one sample row for guidance
	workbook.active.append((
		1, "Sample Course", "Final Assessment", "post", 
		"What is the capital of France?", "London", "Paris", "Berlin", "Rome", "b", 1, "easy", "Geography"
	))
	stream = BytesIO()
	workbook.save(stream)
	stream.seek(0)
	return stream


def question_csv(assessment_id, user_id, role):
	"""Build a CSV export of an assessment without exposing it to students."""
	stream = StringIO()
	writer = csv.DictWriter(stream, fieldnames=QUESTION_COLUMNS)
	writer.writeheader()
	with get_db() as connection:
		assessment = connection.execute("SELECT a.id, a.type, a.title, c.id course_id, c.name course_name, c.created_by FROM assessments a JOIN courses c ON c.id = a.course_id WHERE a.id = ?", (assessment_id,)).fetchone()
		if not assessment or not course_is_manageable(connection, assessment["course_id"], user_id, role):
			return None
		questions = connection.execute("SELECT q.* FROM questions q JOIN assessment_questions aq ON aq.question_id = q.id WHERE aq.assessment_id = ? ORDER BY q.id", (assessment_id,)).fetchall()
	for question in questions:
		writer.writerow({"course_id": assessment["course_id"], "course_name": assessment["course_name"], "assessment_title": assessment["title"], "assessment_type": assessment["type"], "question_text": question["question_text"], "option_a": question["option_a"], "option_b": question["option_b"], "option_c": question["option_c"], "option_d": question["option_d"], "correct_option": question["correct_option"], "marks": question["marks"], "difficulty": question["difficulty"], "topic_tag": question["topic_tag"]})
	return BytesIO(stream.getvalue().encode("utf-8-sig"))


def import_questions(file_obj, user_id, role="admin"):
	"""Import valid Excel rows and return created and rejected counts."""
	if file_obj.filename.lower().endswith(".csv"):
		rows = list(csv.DictReader(TextIOWrapper(file_obj.stream, encoding="utf-8-sig")))
		row_data = rows
	else:
		workbook = load_workbook(file_obj, read_only=True, data_only=True)
		rows = list(workbook.active.iter_rows(values_only=True))
		row_data = (dict(zip(rows[0], values)) for values in rows[1:]) if rows else []
	if not rows:
		return 0, 0
	created = rejected = 0
	with get_db() as connection:
		for data in row_data:
			course_id = data.get("course_id")
			correct = str(data.get("correct_option", "")).lower().strip()
			if not course_id or not data.get("question_text") or correct not in ("a", "b", "c", "d") or any(not data.get(f"option_{key}") for key in "abcd"):
				rejected += 1
				continue
			course = connection.execute("SELECT id, name FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not course or not course_is_manageable(connection, course_id, user_id, role):
				rejected += 1
				continue
			bank_name = f"{data.get('assessment_title') or 'Course'} Question Bank"
			bank = connection.execute("SELECT id FROM question_banks WHERE name = ?", (bank_name,)).fetchone()
			if not bank:
				bank = (connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, 'Imported', ?)", (bank_name, user_id)).lastrowid,)
			question = connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (bank[0], data["question_text"], data["option_a"], data["option_b"], data["option_c"], data["option_d"], correct, int(data.get("marks") or 1), data.get("difficulty") or "medium", data.get("topic_tag") or "", user_id)).lastrowid
			title = data.get("assessment_title") or f"{course['name']} assessment"
			assessment = connection.execute("SELECT id FROM assessments WHERE course_id = ? AND title = ?", (course_id, title)).fetchone()
			if not assessment:
				assessment = (connection.execute("INSERT INTO assessments (course_id, type, title) VALUES (?, ?, ?)", (course_id, str(data.get("assessment_type") or "post").lower(), title)).lastrowid,)
			connection.execute("INSERT OR IGNORE INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (assessment[0], question))
			created += 1
	return created, rejected

def create_app():
	"""Build and configure the Flask application."""
	app = Flask(__name__)
	app.secret_key = os.getenv("LMS_SECRET_KEY", "change-this-local-secret")
	app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
	app.jinja_env.globals["embed_url"] = embed_url
	init_db()

	@app.route("/", methods=["GET", "POST"])
	def home():
		"""Authenticate users and show their permitted courses."""
		if request.method == "POST":
			username = request.form.get("username", "").strip().lower()
			password = request.form.get("password", "")
			with get_db() as connection:
				user = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
			if user and check_password_hash(user["password_hash"], password):
				session.pop("impersonator_id", None)
				session.update(
                    user=user["full_name"], 
                    user_id=user["id"], 
                    actual_role=user["role"], 
                    role="basic user", # Always login as basic user
                    profile_picture=user["profile_picture"] if "profile_picture" in user.keys() else ""
                )
				return redirect(url_for("home"))
			flash("Invalid username or password.")
		with get_db() as connection:
			courses = connection.execute("SELECT DISTINCT c.* FROM courses c LEFT JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE c.created_by = ? OR ca.student_id IS NOT NULL ORDER BY c.id DESC", (session.get("user_id", 0), session.get("user_id", 0))).fetchall()
		with get_db() as connection:
			if session.get("role") in ("admin", "moderator"):
				assessments = connection.execute("SELECT DISTINCT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id LEFT JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE c.created_by = ? OR ca.student_id IS NOT NULL ORDER BY a.id DESC", (session.get("user_id", 0), session.get("user_id", 0))).fetchall()
			else:
				assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE ca.status = 'completed' ORDER BY a.id DESC", (session.get("user_id", 0),)).fetchall()
		return render_template("index.html", user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"), impersonating=session.get("impersonator_id"), courses=courses, assessments=assessments)


	@app.route("/assessment/<int:assessment_id>", methods=["GET", "POST"])
	def assessment(assessment_id):
		"""Show an assessment and store one evaluated student attempt."""
		if not session.get("user_id") or session.get("role") != "basic user":
			return redirect(url_for("home"))
		with get_db() as connection:
			assessment_row = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id JOIN course_assignments ca ON ca.course_id = c.id WHERE a.id = ? AND ca.student_id = ?", (assessment_id, session["user_id"])).fetchone()
			questions = connection.execute("SELECT q.* FROM questions q JOIN assessment_questions aq ON aq.question_id = q.id WHERE aq.assessment_id = ?", (assessment_id,)).fetchall()
		if not assessment_row:
			return redirect(url_for("home"))
		with get_db() as connection:
			is_completed = connection.execute("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ? AND status = 'completed'", (assessment_row["course_id"], session["user_id"])).fetchone()
		if not is_completed:
			flash("Complete the course before starting the assessment.")
			return redirect(url_for("course_detail", course_id=assessment_row["course_id"]))
		if request.method == "POST":
			with get_db() as connection:
				attempt = connection.execute("INSERT INTO assessment_attempts (assessment_id, student_id, status) VALUES (?, ?, 'evaluated')", (assessment_id, session["user_id"]))
				score = 0
				for question in questions:
					selected = request.form.get(f"q{question['id']}")
					correct = selected == question["correct_option"]
					marks = question["marks"] if correct else 0
					score += marks
					connection.execute("INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) VALUES (?, ?, ?, ?, ?)", (attempt.lastrowid, question["id"], selected, correct, marks))
				percentage = (score / max(sum(q["marks"] for q in questions), 1)) * 100
				result = "pass" if percentage >= assessment_row["pass_percentage"] else "fail"
				connection.execute("UPDATE assessment_attempts SET score=?, percentage=?, result=?, submitted_at=CURRENT_TIMESTAMP WHERE id=?", (score, percentage, result, attempt.lastrowid))
			return render_template("assessment.html", assessment=assessment_row, score=score, percentage=percentage, result=result)
		return render_template("assessment.html", assessment=assessment_row, questions=questions)

	@app.get("/course/<int:course_id>")
	def course_detail(course_id):
		"""Show assigned course content and each student's completion state."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			allowed = course_is_visible(connection, course_id, session["user_id"])
			assignment = connection.execute("SELECT status FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"])).fetchone()
			progress = assignment["status"] if assignment else "not_started"
			assessments = connection.execute("SELECT * FROM assessments WHERE course_id = ? ORDER BY id", (course_id,)).fetchall()
		if not course or not allowed:
			return redirect(url_for("home"))
		return render_template("course.html", course=course, progress=progress, assessments=assessments, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"), impersonating=session.get("impersonator_id"))

	@app.post("/course/<int:course_id>/complete")
	def complete_course(course_id):
		"""Mark course as completed for the current student."""
		if not session.get("user_id") or session.get("role") != "basic user":
			return redirect(url_for("home"))
		with get_db() as connection:
			connection.execute("UPDATE course_assignments SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"]))
		return redirect(url_for("course_detail", course_id=course_id))

	@app.route("/admin", methods=["GET", "POST"])
	@staff_required
	def admin_panel():
		"""Create users or courses and assign courses to students."""
		if request.method == "POST":
			action = request.form.get("action")
			if action == "add_user" and session.get("role") == "admin":
				full_name = request.form.get("full_name", "").strip()
				username = request.form.get("username", "").strip().lower()
				password = request.form.get("password", "")
				role = request.form.get("role", "basic user")
				if not full_name or not username or len(password) < 6 or role not in ROLES:
					flash("Enter all fields and use a password of at least 6 characters.")
				else:
					try:
						with get_db() as connection:
							connection.execute("INSERT INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)", (full_name, username, generate_password_hash(password), role))
						flash("User added successfully.")
					except sqlite3.IntegrityError:
						flash("That username already exists.")
			elif action == "update_user" and session.get("role") == "admin":
				with get_db() as connection:
					connection.execute("UPDATE users SET full_name = ?, username = ?, role = ? WHERE id = ? AND id != ?", (request.form["full_name"].strip(), request.form["username"].strip().lower(), request.form["role"], request.form["record_id"], session["user_id"]))
				flash("User updated successfully.")
			elif action == "add_course":
				name = request.form.get("course_name", "").strip()
				description = request.form.get("description", "").strip()
				category = request.form.get("category", "General").strip() or "General"
				content_type = request.form.get("content_type", "")
				try:
					content_url = content_location("course_file")
				except ValueError as error:
					content_url = None
					flash(str(error))
				if not name or content_type not in CONTENT_TYPES or not content_url:
					flash("Enter a course name and provide a valid link or supported file.")
				else:
					with get_db() as connection:
						cursor = connection.execute("INSERT INTO courses (name, description, category, content_type, content_url, created_by) VALUES (?, ?, ?, ?, ?, ?)", (name, description, category, content_type, content_url, session["user_id"]))
						connection.execute("INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'create', 'course', ?)", (session["user_id"], cursor.lastrowid))
					flash("Course created successfully.")
			elif action == "update_course":
				with get_db() as connection:
					if course_is_manageable(connection, request.form["record_id"], session["user_id"], session["role"]):
						connection.execute("UPDATE courses SET name = ?, description = ?, category = ?, status = ? WHERE id = ?", (request.form["name"].strip(), request.form.get("description", "").strip(), request.form.get("category", "General").strip(), request.form.get("status", "published"), request.form["record_id"]))
						flash("Course updated successfully.")

			elif action == "add_bank":
				with get_db() as connection:
					connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, ?, ?)", (request.form["bank_name"].strip(), request.form.get("category", "General").strip(), session["user_id"]))
				flash("Question bank created successfully.")
			elif action == "add_question":
				with get_db() as connection:
					assessment = connection.execute("SELECT course_id, title FROM assessments WHERE id = ?", (request.form["assessment_id"],)).fetchone()
					if assessment and course_is_manageable(connection, assessment["course_id"], session["user_id"], session["role"]):
						bank_name = f"{assessment['title']} Question Bank"
						bank = connection.execute("SELECT id FROM question_banks WHERE name = ?", (bank_name,)).fetchone()
						if not bank:
							bank = (connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, 'Manual', ?)", (bank_name, session["user_id"])).lastrowid,)
						question_id = connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (bank[0], request.form["question_text"].strip(), request.form["option_a"].strip(), request.form["option_b"].strip(), request.form["option_c"].strip(), request.form["option_d"].strip(), request.form["correct_option"], int(request.form.get("marks", 1)), request.form.get("difficulty", "medium"), session["user_id"])).lastrowid
						connection.execute("INSERT INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (request.form["assessment_id"], question_id))
						flash("Question added and linked to assessment successfully.")
					else:
						flash("You can only manage courses you created.")
			elif action == "add_assessment":
				with get_db() as connection:
					if course_is_manageable(connection, request.form["course_id"], session["user_id"], session["role"]):
						connection.execute("INSERT INTO assessments (course_id, type, title, pass_percentage, max_attempts) VALUES (?, ?, ?, ?, ?)", (request.form["course_id"], request.form["assessment_type"], request.form["assessment_title"].strip(), request.form.get("pass_percentage", 60), request.form.get("max_attempts", 1)))
						flash("Assessment created successfully.")
					else:
						flash("You can only manage courses you created.")
			elif action == "import_questions":
				file_obj = request.files.get("question_file")
				if not file_obj or not file_obj.filename.lower().endswith((".xlsx", ".csv")):
					flash("Upload an .xlsx or .csv question file.")
				else:
					try:
						created, rejected = import_questions(file_obj, session["user_id"], session["role"])
						flash(f"Imported {created} questions; rejected {rejected} rows.")
					except (ValueError, KeyError, TypeError):
						flash("The workbook format is invalid. Download and use the template.")
			elif action == "update_assessment":
				with get_db() as connection:
					course = connection.execute("SELECT course_id FROM assessments WHERE id = ?", (request.form["record_id"],)).fetchone()
					if course and course_is_manageable(connection, course["course_id"], session["user_id"], session["role"]):
						connection.execute("UPDATE assessments SET title = ?, type = ?, pass_percentage = ?, max_attempts = ? WHERE id = ?", (request.form["title"].strip(), request.form["type"], request.form["pass_percentage"], request.form["max_attempts"], request.form["record_id"]))
						flash("Assessment updated successfully.")
			elif action == "assign_course":
				try:
					with get_db() as connection:
						if not course_is_manageable(connection, request.form["course_id"], session["user_id"], session["role"]):
							flash("You can only manage courses you created.")
							return redirect(url_for("admin_panel"))
						connection.execute("INSERT INTO course_assignments (course_id, student_id) VALUES (?, ?)", (request.form["course_id"], request.form["student_id"]))
					flash("Course assigned successfully.")
				except (sqlite3.IntegrityError, KeyError):
					flash("That course is already assigned to this student.")
		with get_db() as connection:
			users = connection.execute("SELECT u.id, u.full_name, u.username, u.role, COALESCE(GROUP_CONCAT(ca.course_id), '') AS course_ids FROM users u LEFT JOIN course_assignments ca ON ca.student_id = u.id GROUP BY u.id ORDER BY u.id").fetchall()
			courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY c.id DESC", (session["user_id"], session["user_id"])).fetchall()
			students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user' ORDER BY full_name").fetchall()
			banks = connection.execute("SELECT * FROM question_banks ORDER BY id DESC").fetchall()
			assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY a.id DESC", (session["user_id"], session["user_id"])).fetchall()
		return render_template("admin.html", users=users, courses=courses, students=students, banks=banks, assessments=assessments, content_types=CONTENT_TYPES, roles=ROLES, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/admin/reports")
	@admin_required
	def reports():
		"""Show row counts for every LMS table."""
		with get_db() as connection:
			tables = [row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
			report = [(table, connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]) for table in tables]
		return render_template("reports.html", report=report, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/admin/question-template")
	@staff_required
	def download_question_template():
		"""Download the Excel question and assessment template."""
		return send_file(question_template(), as_attachment=True, download_name="learnly_questions_template.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

	@app.post("/admin/delete/<resource>/<int:record_id>")
	@admin_required
	def delete_record(resource, record_id):
		"""Delete an approved admin resource and report dependency conflicts."""
		allowed = {"user": "users", "course": "courses", "module": "modules", "assessment": "assessments"}
		table = allowed.get(resource)
		if not table or resource == "user" and record_id == session.get("user_id"):
			flash("This record cannot be deleted.")
			return redirect(url_for("admin_panel"))
		try:
			with get_db() as connection:
				cursor = connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
				if cursor.rowcount:
					flash(f"{resource.title()} deleted successfully.")
				else:
					flash("Record not found.")
		except sqlite3.IntegrityError:
			flash("This record is still in use and cannot be deleted.")
		return redirect(url_for("admin_panel"))

	@app.get("/assessments/<int:assessment_id>/questions/download")
	def download_assessment_questions(assessment_id):
		"""Download assessment questions for admins or owning moderators only."""
		if session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
		stream = question_csv(assessment_id, session["user_id"], session["role"])
		if stream is None:
			return redirect(url_for("admin_panel"))
		return send_file(stream, as_attachment=True, download_name=f"assessment-{assessment_id}-questions.csv", mimetype="text/csv")


	@app.get("/courses")
	@staff_required
	def courses_page():
		"""Dedicated course management page with wizard."""
		with get_db() as connection:
			courses = connection.execute(
				"SELECT c.*, u.full_name AS creator_name FROM courses c JOIN users u ON u.id = c.created_by ORDER BY c.id DESC"
			).fetchall()
		return render_template("courses.html",
			courses=courses,
			content_types=CONTENT_TYPES,
			user=session.get("user"),
			role=session.get("role"),
			actual_role=session.get("actual_role"),
			profile_picture=session.get("profile_picture")
		)

	@app.route("/courses/create", methods=["POST"])
	@staff_required
	def courses_create():
		"""Handle course creation wizard final submission."""
		name = request.form.get("name", "").strip()
		description = request.form.get("description", "").strip()
		category = request.form.get("category", "General").strip() or "General"
		difficulty = request.form.get("difficulty", "beginner")
		duration_minutes = int(request.form.get("duration_minutes", 0) or 0)
		tags = request.form.get("tags", "").strip()
		thumbnail_color = request.form.get("thumbnail_color", "#6366f1")
		status = request.form.get("status", "draft")
		content_type = request.form.get("content_type", "")

		errors = []
		if not name:
			errors.append("Course title is required.")
		if len(name) > 200:
			errors.append("Course title must be under 200 characters.")
		if content_type not in CONTENT_TYPES:
			errors.append("Please select a valid content type.")

		content_url = None
		if not errors:
			try:
				content_url = content_location("course_file")
			except ValueError:
				content_url = None

		if not content_url:
			errors.append("Please provide a valid URL or upload a supported file.")

		if errors:
			for e in errors:
				flash(e)
			return redirect(url_for("courses_page"))

		with get_db() as connection:
			cursor = connection.execute(
				"INSERT INTO courses (name, description, category, content_type, content_url, created_by, status, tags, duration_minutes, difficulty, thumbnail_color) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
				(name, description, category, content_type, content_url, session["user_id"], status, tags, duration_minutes, difficulty, thumbnail_color)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'create', 'course', ?)",
				(session["user_id"], cursor.lastrowid)
			)
		flash(f"Course '{name}' created successfully.")
		return redirect(url_for("courses_page"))

	@app.post("/courses/<int:course_id>/update")
	@staff_required
	def courses_update(course_id):
		"""Inline update a course from the course list."""
		with get_db() as connection:
			if not course_is_manageable(connection, course_id, session["user_id"], session["role"]):
				flash("You can only edit courses you created.")
				return redirect(url_for("courses_page"))
			connection.execute(
				"UPDATE courses SET name=?, description=?, category=?, status=?, tags=?, duration_minutes=?, difficulty=?, thumbnail_color=? WHERE id=?",
				(
					request.form.get("name", "").strip(),
					request.form.get("description", "").strip(),
					request.form.get("category", "General").strip() or "General",
					request.form.get("status", "draft"),
					request.form.get("tags", "").strip(),
					int(request.form.get("duration_minutes", 0) or 0),
					request.form.get("difficulty", "beginner"),
					request.form.get("thumbnail_color", "#6366f1"),
					course_id
				)
			)
		flash("Course updated.")
		return redirect(url_for("courses_page"))


	@app.get("/view-as")
	@admin_required
	def view_as_page():
		with get_db() as connection:
			students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user' ORDER BY full_name").fetchall()
		return render_template("view_as.html", students=students, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/admin/view-as/<int:user_id>")
	@admin_required
	def view_as(user_id):
		"""Start an admin-only session view as another user."""
		with get_db() as connection:
			target = connection.execute("SELECT id, full_name, role FROM users WHERE id = ?", (user_id,)).fetchone()
		if not target:
			return redirect(url_for("admin_panel"))
		session["impersonator_id"] = session["user_id"]
		session.update(user=target["full_name"], user_id=target["id"], role=target["role"])
		return redirect(url_for("home"))

	@app.get("/admin/exit-view")
	def exit_view():
		"""Restore the administrator after a view-as session."""
		admin_id = session.get("impersonator_id")
		if not admin_id:
			return redirect(url_for("home"))
		with get_db() as connection:
			admin = connection.execute("SELECT id, full_name, role FROM users WHERE id = ? AND role = 'admin'", (admin_id,)).fetchone()
		if not admin:
			session.clear()
			return redirect(url_for("home"))
		session.pop("impersonator_id", None)
		session.update(user=admin["full_name"], user_id=admin["id"], role=admin["role"])
		return redirect(url_for("admin_panel"))

	@app.get("/uploads/<path:filename>")
	def uploaded_file(filename):
		"""Serve locally stored course content."""
		return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)

	@app.get("/switch-role")
	def switch_role():
		"""Toggle between basic user and admin view for staff."""
		if "user_id" not in session or session.get("actual_role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
		
		# Toggle the active role
		if session.get("role") == "basic user":
			session["role"] = session.get("actual_role")
		else:
			session["role"] = "basic user"
			
		return redirect(url_for("home"))

	@app.route("/profile", methods=["GET", "POST"])
	def profile():
		"""Allow users to edit their profile."""
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		if request.method == "POST":
			full_name = request.form.get("full_name", "").strip()
			email = request.form.get("email", "").strip()
			phone_number = request.form.get("phone_number", "").strip()
			
			pic = request.files.get("profile_picture")
			pic_filename = session.get("profile_picture", "")
			
			if pic and pic.filename:
				try:
					from storage import save_file
					# We can reuse save_file for images if we add image extensions, but let's just save it.
					import os
					from werkzeug.utils import secure_filename
					from uuid import uuid4
					ext = os.path.splitext(pic.filename)[1].lower()
					if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
						pic_filename = uuid4().hex + ext
						pic.save(os.path.join(UPLOAD_FOLDER, pic_filename))
				except Exception as e:
					flash("Failed to save profile picture.")
					
			with get_db() as connection:
				connection.execute(
					"UPDATE users SET full_name = ?, email = ?, phone_number = ?, profile_picture = ? WHERE id = ?",
					(full_name, email, phone_number, pic_filename, session["user_id"])
				)
			session["user"] = full_name
			session["profile_picture"] = pic_filename
			flash("Profile updated successfully.")
			return redirect(url_for("profile"))
			
		with get_db() as connection:
			user_data = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
		return render_template("profile.html", user_data=user_data, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))


	@app.get("/logout")
	def logout():
		"""End the current session."""
		session.clear()
		return redirect(url_for("home"))

	return app


app = create_app()


if __name__ == "__main__":
	app.run(debug=True)
