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
from werkzeug.utils import secure_filename
from uuid import uuid4
from flask import Flask, flash, redirect, render_template, request, send_file, send_from_directory, session, url_for
from openpyxl import Workbook, load_workbook
from storage import save_file


DATABASE = Path(os.getenv("LMS_DATABASE", Path(__file__).with_name("users.db")))
UPLOAD_FOLDER = Path(os.getenv("LMS_UPLOAD_FOLDER", Path(__file__).with_name("uploads")))
ROLES = ("admin", "moderator", "basic user")

CONTENT_TYPES = ("URL", "PDF", "Video", "PPT")
QUESTION_COLUMNS = ("course_id", "course_name", "assessment_title", "assessment_type", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_option", "marks", "difficulty", "topic_tag", "explanation")


def get_db():
	"""Open a row-producing SQLite connection with foreign keys enabled."""
	DATABASE.parent.mkdir(parents=True, exist_ok=True)
	connection = sqlite3.connect(DATABASE)
	connection.row_factory = sqlite3.Row
	connection.execute("PRAGMA foreign_keys = ON")
	return connection


def process_reward_event(connection, user_id, event_name, source_reference_id, source_reference_type, description, input_value=None, actor_id=None):
	"""
	Central Reward Engine function.
	Calculates and registers reward transactions, maintaining a ledger and wallet balance.
	Avoids duplicates using idempotent checks and handles rating diffs.
	"""
	# 1. Lookup reward source rule
	source = connection.execute("SELECT * FROM reward_sources WHERE name = ?", (event_name,)).fetchone()
	if not source or source["status"] != "active":
		return 0

	# 2. Calculate point output
	points = 0
	if source["calculation_type"] == "MULTIPLIER":
		if input_value is None:
			input_value = 0
		points = int(float(input_value) * float(source["multiplier"]))
	elif source["calculation_type"] == "FIXED":
		points = int(source["fixed_points"])

	# 3. Check for duplicates / updates
	prev_sum = connection.execute(
		"""SELECT COALESCE(SUM(points), 0) AS total 
		   FROM reward_transactions 
		   WHERE user_id = ? AND reward_source = ? AND source_reference_id = ? AND source_reference_type = ?""",
		(user_id, event_name, str(source_reference_id), source_reference_type)
	).fetchone()["total"]

	# If this is a FIXED type and it has already been awarded, do NOT award it again.
	if source["calculation_type"] == "FIXED" and prev_sum != 0:
		return 0

	points_to_award = points - prev_sum
	if points_to_award == 0:
		return 0

	# 4. Determine transaction type
	tx_type = "EARN"
	if prev_sum != 0:
		tx_type = "ADJUSTMENT"
		if points_to_award < 0:
			tx_type = "REVERSAL"

	# 5. Fetch/initialize user wallet
	wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
	if not wallet:
		connection.execute("INSERT INTO user_wallets (user_id, current_balance, total_earned, total_settled, total_adjusted) VALUES (?, 0, 0, 0, 0)", (user_id,))
		balance_before = 0
		total_earned = 0
		total_settled = 0
		total_adjusted = 0
	else:
		balance_before = wallet["current_balance"]
		total_earned = wallet["total_earned"]
		total_settled = wallet["total_settled"]
		total_adjusted = wallet["total_adjusted"]

	balance_after = balance_before + points_to_award

	# 6. Insert transaction ledger entry
	connection.execute(
		"""INSERT INTO reward_transactions 
		   (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
		   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
		(user_id, event_name, str(source_reference_id), source_reference_type, description, points_to_award, tx_type, balance_before, balance_after, actor_id)
	)

	# 7. Update wallet totals
	if tx_type == "EARN":
		total_earned += points_to_award
	elif tx_type in ("ADJUSTMENT", "REVERSAL"):
		total_adjusted += abs(points_to_award)

	connection.execute(
		"""UPDATE user_wallets 
		   SET current_balance = ?, total_earned = ?, total_adjusted = ?, updated_at = CURRENT_TIMESTAMP 
		   WHERE user_id = ?""",
		(balance_after, total_earned, total_adjusted, user_id)
	)

	return points_to_award


def init_db():
	"""Create the LMS schema and seed the first administrator."""
	with get_db() as connection:
		# â”€â”€ Core tables â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
		connection.execute("""
			CREATE TABLE IF NOT EXISTS users (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
			CREATE TABLE IF NOT EXISTS groups (
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				description TEXT DEFAULT '',
				group_type TEXT DEFAULT '',
				status TEXT DEFAULT 'active',
				created_by INTEGER NOT NULL REFERENCES users(id),
				created_at TEXT DEFAULT CURRENT_TIMESTAMP
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS group_members (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				employee_id TEXT DEFAULT '',
				email TEXT DEFAULT '',
				department TEXT DEFAULT '',
				location TEXT DEFAULT '',
				user_status TEXT DEFAULT 'active',
				added_at TEXT DEFAULT CURRENT_TIMESTAMP,
				UNIQUE(group_id, user_id)
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS group_course_assignments (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
				course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
				assigned_by INTEGER NOT NULL REFERENCES users(id),
				assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
				status TEXT DEFAULT 'active',
				UNIQUE(group_id, course_id)
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS assignment_history (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
				course_name TEXT NOT NULL,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				user_name TEXT NOT NULL,
				assignment_source TEXT NOT NULL CHECK (assignment_source IN ('Individual', 'Group')),
				group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
				group_name TEXT,
				assigned_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				assigned_by_name TEXT,
				assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
				assignment_status TEXT DEFAULT 'attempted',
				duplicate_check_result TEXT DEFAULT 'new'
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS course_assignments (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
				student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				status TEXT DEFAULT 'not_started',
				completed_at TEXT,
				PRIMARY KEY (course_id, student_id)
			)
		""")
		connection.execute("""
			CREATE TABLE IF NOT EXISTS course_certifications (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
				user_name TEXT NOT NULL,
				course_name TEXT NOT NULL,
				course_start_date TEXT,
				course_completion_date TEXT,
				assessment_score REAL DEFAULT 0,
				pass_mark INTEGER DEFAULT 0,
				assessment_attempts INTEGER DEFAULT 0,
				latest_assessment_status TEXT DEFAULT 'NOT_STARTED',
				feedback_rating INTEGER,
				feedback_comments TEXT DEFAULT '',
				feedback_submitted_at TEXT,
				certificate_id TEXT,
				certificate_generated_at TEXT,
				badge TEXT DEFAULT 'NOT CERTIFIED',
				certification_status TEXT DEFAULT 'NOT_STARTED',
				UNIQUE(user_id, course_id)
			)
		""")
		connection.execute("CREATE INDEX IF NOT EXISTS idx_assignments_student ON course_assignments(student_id)")
		connection.execute("CREATE INDEX IF NOT EXISTS idx_courses_creator ON courses(created_by)")
		connection.execute("CREATE INDEX IF NOT EXISTS idx_course_certifications_user_course ON course_certifications(user_id, course_id)")

		# â”€â”€ Migrate users table for group metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
		user_columns = [col[1] for col in connection.execute("PRAGMA table_info(users)").fetchall()]
		for column, column_sql in (
			("employee_id", "ALTER TABLE users ADD COLUMN employee_id TEXT DEFAULT ''"),
			("department", "ALTER TABLE users ADD COLUMN department TEXT DEFAULT ''"),
			("location", "ALTER TABLE users ADD COLUMN location TEXT DEFAULT ''"),
			("is_active", "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1"),
		):
			if column not in user_columns:
				connection.execute(column_sql)

		# â”€â”€ Migrate courses table if old schema (missing PPT or extra columns) â”€â”€
		table_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'courses'").fetchone()[0]
		if "'PPT'" not in table_sql:
			connection.execute("ALTER TABLE courses RENAME TO courses_legacy")
			connection.execute("CREATE TABLE courses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, content_type TEXT NOT NULL CHECK (content_type IN ('URL', 'PDF', 'Video', 'PPT')), content_url TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), description TEXT DEFAULT '', category TEXT DEFAULT 'General', status TEXT DEFAULT 'published')")
			connection.execute("INSERT INTO courses (id, name, content_type, content_url, created_by) SELECT id, name, content_type, content_url, created_by FROM courses_legacy")
			connection.execute("DROP TABLE courses_legacy")

		# â”€â”€ Migrate course_assignments: add status/completed_at if missing â”€â”€â”€â”€â”€â”€
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

		# â”€â”€ Migrate questions table: add explanation if missing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
		cursor = connection.execute("PRAGMA table_info(questions)")
		columns = [row[1] for row in cursor.fetchall()]
		cursor.close()
		if columns and "explanation" not in columns:
			connection.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")

		# â”€â”€ Remaining tables (assessments, questions, etc.) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
		connection.executescript("""
			CREATE TABLE IF NOT EXISTS question_banks (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT DEFAULT 'General', created_by INTEGER NOT NULL REFERENCES users(id));
			CREATE TABLE IF NOT EXISTS questions (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, question_bank_id INTEGER NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE, question_text TEXT NOT NULL, option_a TEXT NOT NULL, option_b TEXT NOT NULL, option_c TEXT NOT NULL, option_d TEXT NOT NULL, correct_option TEXT NOT NULL, marks INTEGER DEFAULT 1, difficulty TEXT DEFAULT 'medium', topic_tag TEXT DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id), explanation TEXT);
			CREATE TABLE IF NOT EXISTS assessments (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, type TEXT NOT NULL, title TEXT NOT NULL, pass_percentage INTEGER DEFAULT 60, max_attempts INTEGER DEFAULT 1);
			CREATE TABLE IF NOT EXISTS assessment_questions (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE, PRIMARY KEY(assessment_id, question_id));
			CREATE TABLE IF NOT EXISTS assessment_attempts (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, attempt_no INTEGER DEFAULT 1, score INTEGER DEFAULT 0, percentage REAL DEFAULT 0, status TEXT DEFAULT 'in_progress', result TEXT DEFAULT 'fail', started_at TEXT DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT);
			CREATE TABLE IF NOT EXISTS attempt_answers (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id), selected_option TEXT, is_correct INTEGER DEFAULT 0, marks_awarded INTEGER DEFAULT 0, UNIQUE(attempt_id, question_id));
			CREATE TABLE IF NOT EXISTS certificates (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES users(id), course_id INTEGER NOT NULL REFERENCES courses(id), cert_uid TEXT UNIQUE NOT NULL, issued_date TEXT DEFAULT CURRENT_DATE, file_url TEXT);
			CREATE TABLE IF NOT EXISTS notifications (
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, type TEXT DEFAULT 'system', is_read INTEGER DEFAULT 0, target_url TEXT DEFAULT '#', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
			CREATE TABLE IF NOT EXISTS audit_logs (
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
			CREATE TABLE IF NOT EXISTS api_credentials (
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, api_key TEXT UNIQUE NOT NULL, api_secret TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT CHECK(status IN ('active', 'inactive')) DEFAULT 'active');
			
			CREATE TABLE IF NOT EXISTS posts (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				title TEXT NOT NULL,
				description TEXT NOT NULL,
				content_type TEXT CHECK(content_type IN ('Text/Article', 'PDF', 'Video', 'Image', 'PPT/PowerPoint')) DEFAULT 'Text/Article',
				category TEXT DEFAULT 'General',
				topic_tag TEXT DEFAULT '',
				created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				status TEXT CHECK(status IN ('DRAFT', 'PENDING_APPROVAL', 'PUBLISHED', 'REJECTED', 'UNPUBLISHED')) DEFAULT 'DRAFT',
				published_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				published_at TEXT,
				version_number INTEGER DEFAULT 1,
				thumbnail TEXT,
				views INTEGER DEFAULT 0
			);
			CREATE TABLE IF NOT EXISTS post_attachments (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
				file_name TEXT NOT NULL,
				file_type TEXT,
				file_path TEXT NOT NULL,
				file_size INTEGER,
				uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
			);
			CREATE TABLE IF NOT EXISTS post_ratings (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				rating INTEGER CHECK(rating >= 1 AND rating <= 5) NOT NULL,
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				UNIQUE(post_id, user_id)
			);
			CREATE TABLE IF NOT EXISTS post_comments (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				comment_text TEXT NOT NULL,
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				status TEXT DEFAULT 'active'
			);
			CREATE TABLE IF NOT EXISTS post_approval_history (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
				version_number INTEGER NOT NULL,
				submitted_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
				reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				reviewed_at TEXT,
				action TEXT CHECK(action IN ('SUBMIT', 'APPROVE', 'REJECT', 'REQUEST_CHANGES')),
				comments TEXT,
				previous_status TEXT,
				new_status TEXT
			);
			
			CREATE TABLE IF NOT EXISTS reward_sources (
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				name TEXT PRIMARY KEY,
				status TEXT CHECK(status IN ('active', 'inactive')) DEFAULT 'active',
				calculation_type TEXT CHECK(calculation_type IN ('MULTIPLIER', 'FIXED')),
				multiplier REAL DEFAULT 1.0,
				fixed_points INTEGER DEFAULT 0
			);
			
			CREATE TABLE IF NOT EXISTS reward_transactions (
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				reward_source TEXT NOT NULL REFERENCES reward_sources(name),
				source_reference_id TEXT NOT NULL,
				source_reference_type TEXT NOT NULL,
				description TEXT NOT NULL,
				points INTEGER NOT NULL,
				transaction_type TEXT CHECK(transaction_type IN ('EARN', 'ADJUSTMENT', 'SETTLEMENT', 'REVERSAL')) DEFAULT 'EARN',
				balance_before INTEGER NOT NULL,
				balance_after INTEGER NOT NULL,
				created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
				created_at TEXT DEFAULT CURRENT_TIMESTAMP,
				status TEXT DEFAULT 'completed',
				settlement_id TEXT
			);
			
			CREATE TABLE IF NOT EXISTS user_wallets (
				user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
				current_balance INTEGER DEFAULT 0,
				total_earned INTEGER DEFAULT 0,
				total_settled INTEGER DEFAULT 0,
				total_adjusted INTEGER DEFAULT 0,
				updated_at TEXT DEFAULT CURRENT_TIMESTAMP
			);
			
			INSERT OR IGNORE INTO reward_sources (name, status, calculation_type, multiplier, fixed_points) VALUES
			('COURSE_CERTIFICATION', 'active', 'MULTIPLIER', 100.0, 0),
			('COURSE_OWNER_RATING', 'active', 'MULTIPLIER', 10.0, 0),
			('COMMUNITY_POST_RATING', 'active', 'MULTIPLIER', 1.0, 0),
			('RATING_GIVEN', 'active', 'FIXED', 0.0, 2),
			('MANUAL_SETTLEMENT', 'active', 'FIXED', 0.0, 0),
			('MANUAL_ADJUSTMENT', 'active', 'FIXED', 0.0, 0),
			('GLOBAL_RESET', 'active', 'FIXED', 0.0, 0),
			('USER_RESET', 'active', 'FIXED', 0.0, 0);
			
			CREATE INDEX IF NOT EXISTS idx_questions_bank ON questions(question_bank_id);
			CREATE INDEX IF NOT EXISTS idx_attempt_student ON assessment_attempts(student_id);
			CREATE INDEX IF NOT EXISTS idx_posts_creator ON posts(created_by);
			CREATE INDEX IF NOT EXISTS idx_post_ratings_post ON post_ratings(post_id);
			CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments(post_id);
			CREATE INDEX IF NOT EXISTS idx_reward_tx_user ON reward_transactions(user_id);
			CREATE INDEX IF NOT EXISTS idx_reward_tx_src ON reward_transactions(reward_source, source_reference_id);
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

		connection.execute("INSERT OR IGNORE INTO users (full_name, username, password_hash, role, employee_id) VALUES (?, ?, ?, ?, ?)", (name, username, generate_password_hash("learn123"), role, f"EMP-{len(columns) + 1:04d}" if role == "moderator" else f"EMP-{abs(hash(username)) % 9000 + 1000:04d}"))

	# Create 100 additional sample users with mandatory employee IDs.
	for idx in range(1, 101):
		full_name = f"Sample User {idx}"
		username = f"sampleuser{idx:03d}"
		employee_id = f"EMP-{idx:04d}"
		role = "basic user" if idx % 10 != 0 else "moderator"
		connection.execute(
			"INSERT OR IGNORE INTO users (full_name, username, password_hash, role, employee_id, department, location, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(full_name, username, generate_password_hash("learn123"), role, employee_id, "Operations", "Hyderabad", 1),
		)
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


def api_required(view):
	"""Decorator to authenticate API requests using X-API-Key and X-API-Secret headers."""
	@wraps(view)
	def wrapped(*args, **kwargs):
		api_key = request.headers.get("X-API-Key")
		api_secret = request.headers.get("X-API-Secret")
		if not api_key or not api_secret:
			return {"error": "Missing X-API-Key or X-API-Secret header."}, 401
		
		with get_db() as connection:
			creds = connection.execute(
				"SELECT ac.*, u.username, u.role, u.full_name FROM api_credentials ac JOIN users u ON u.id = ac.user_id WHERE ac.api_key = ? AND ac.api_secret = ? AND ac.status = 'active'",
				(api_key, api_secret)
			).fetchone()
			
			if not creds:
				return {"error": "Invalid or inactive API credentials."}, 401
				
			# Store authenticated user in request context
			from flask import g
			g.api_user = {
				"id": creds["user_id"],
				"username": creds["username"],
				"role": creds["role"],
				"full_name": creds["full_name"]
			}
		return view(*args, **kwargs)
	return wrapped


def api_staff_required(view):
	"""Restrict API endpoint to administrators and moderators."""
	@wraps(view)
	@api_required
	def wrapped(*args, **kwargs):
		from flask import g
		if g.api_user["role"] not in ("admin", "moderator"):
			return {"error": "Access forbidden: staff permissions required."}, 403
		return view(*args, **kwargs)
	return wrapped


def api_admin_required(view):
	"""Restrict API endpoint to administrators only."""
	@wraps(view)
	@api_required
	def wrapped(*args, **kwargs):
		from flask import g
		if g.api_user["role"] != "admin":
			return {"error": "Access forbidden: administrator permissions required."}, 403
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


def detect_content_type(value):
	"""Auto-detect the content type ('PDF', 'Video', 'PPT', 'URL') from a URL or filename."""
	import urllib.request
	val = (value or "").strip()
	if not val:
		return "URL"
	
	val_lower = val.lower()

	# If it's a URL, attempt a quick HTTP request to inspect headers
	if val_lower.startswith("http://") or val_lower.startswith("https://"):
		if any(domain in val_lower for domain in ("youtube.com", "youtu.be", "vimeo.com")):
			return "Video"
		try:
			req = urllib.request.Request(
				val, 
				headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
				method='HEAD'
			)
			with urllib.request.urlopen(req, timeout=1.0) as resp:
				mime = (resp.headers.get_content_type() or "").lower()
		except Exception:
			try:
				req = urllib.request.Request(
					val, 
					headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
				)
				with urllib.request.urlopen(req, timeout=1.0) as resp:
					mime = (resp.headers.get_content_type() or "").lower()
			except Exception:
				mime = ""
		
		if mime:
			if "pdf" in mime:
				return "PDF"
			if "video" in mime:
				return "Video"
			if "powerpoint" in mime or "presentation" in mime or "officedocument.presentationml" in mime:
				return "PPT"

	if any(ext in val_lower for ext in (".mp4", ".webm", ".mov", ".avi", ".mkv")):
		return "Video"
	if any(domain in val_lower for domain in ("youtube.com", "youtu.be", "vimeo.com")):
		return "Video"
	if val_lower.endswith(".pdf") or ".pdf?" in val_lower or "/pdf/" in val_lower or "-pdf" in val_lower:
		return "PDF"
	if any(ext in val_lower for ext in (".ppt", ".pptx", ".pps")):
		return "PPT"
	return "URL"


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
	"""Return whether a user is assigned to, created, or if the course is published."""
	user = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
	role = user["role"] if user else "basic user"
	course = connection.execute("SELECT status, created_by FROM courses WHERE id = ?", (course_id,)).fetchone()
	if not course: return False
	if course["created_by"] == user_id or role == 'admin': return True
	return course["status"] == 'published'



def course_is_manageable(connection, course_id, user_id, role):
	"""Return whether a staff user may manage a course."""
	return role == "admin" or connection.execute("SELECT 1 FROM courses WHERE id = ? AND created_by = ?", (course_id, user_id)).fetchone() is not None


def get_course_status_label(value):
	"""Normalize the course assignment status to the required business states."""
	mapped = {
		"not_started": "NOT_STARTED",
		"in_progress": "IN_PROGRESS",
		"assessment_pending": "ASSESSMENT_PENDING",
		"assessment_failed": "ASSESSMENT_FAILED",
		"feedback_pending": "FEEDBACK_PENDING",
		"certified": "CERTIFIED",
		"completed": "ASSESSMENT_PENDING",
	}
	return mapped.get((value or "").strip().lower(), "NOT_STARTED")


def determine_badge(score, pass_mark=60):
	"""Compute the badge from the final certified assessment percentage."""
	if score < pass_mark:
		return "NOT CERTIFIED"
	if score >= 91:
		return "PLATINUM"
	if score >= 80:
		return "GOLD"
	if score >= 70:
		return "SILVER"
	return "BRONZE"


def get_user_course_record(connection, user_id, course_id):
	"""Fetch the current certification record for a user/course pair."""
	return connection.execute(
		"SELECT * FROM course_certifications WHERE user_id = ? AND course_id = ?",
		(user_id, course_id),
	).fetchone()


def user_has_course_access(connection, user_id, course_id):
	"""Check whether a user already has an active course assignment."""
	return connection.execute(
		"SELECT 1 FROM course_assignments WHERE student_id = ? AND course_id = ? LIMIT 1",
		(user_id, course_id),
	).fetchone() is not None


def create_group_assignment_history(connection, course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, duplicate_check_result, assignment_status="attempted"):
	"""Record assignment attempts and deduplication decisions for audit reporting."""
	connection.execute(
		"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
		(course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result),
	)


def question_template():
	"""Build a blank Excel template for course assessment questions."""
	workbook = Workbook()
	workbook.active.append(QUESTION_COLUMNS)
	# Pre-fill one sample row for guidance
	workbook.active.append((
		1, "Sample Course", "Final Assessment", "post", 
		"What is the capital of France?", "London", "Paris", "Berlin", "Rome", "b", 1, "easy", "Geography", "Paris is the capital of France."
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
		writer.writerow({"course_id": assessment["course_id"], "course_name": assessment["course_name"], "assessment_title": assessment["title"], "assessment_type": assessment["type"], "question_text": question["question_text"], "option_a": question["option_a"], "option_b": question["option_b"], "option_c": question["option_c"], "option_d": question["option_d"], "correct_option": question["correct_option"], "marks": question["marks"], "difficulty": question["difficulty"], "topic_tag": question["topic_tag"], "explanation": question["explanation"]})
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
			explanation = str(data.get("explanation", "")).strip() if data.get("explanation") else None
			question = connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (bank[0], data["question_text"], data["option_a"], data["option_b"], data["option_c"], data["option_d"], correct, int(data.get("marks") or 1), data.get("difficulty") or "medium", data.get("topic_tag") or "", user_id, explanation)).lastrowid
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
			courses = connection.execute("""
				SELECT 
					c.*,
					creator.full_name AS course_owner,
					(SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ca.student_id ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by,
					ca.status AS progress_status,
					ca.updated_at AS last_accessed,
					ca.completed_at AS completion_date,
					ca.created_at AS assigned_on,
					cc.certification_status,
					cc.badge,
					(SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS avg_rating,
					(SELECT COUNT(*) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS rating_count
				FROM courses c 
				JOIN course_assignments ca ON ca.course_id = c.id 
				LEFT JOIN users creator ON c.created_by = creator.id
				LEFT JOIN course_certifications cc ON cc.course_id = c.id AND cc.user_id = ca.student_id
				WHERE ca.student_id = ? 
				  AND (c.status = 'published' OR c.created_by = ? OR ? = 'admin')
				ORDER BY c.id DESC
			""", (session.get("user_id", 0), session.get("user_id", 0), session.get("role", "basic user"))).fetchall()
			
			leaderboard = connection.execute(
				"""SELECT w.current_balance, u.full_name, u.username
				   FROM user_wallets w
				   JOIN users u ON u.id = w.user_id
				   ORDER BY w.current_balance DESC
				   LIMIT 5"""
			).fetchall()
			
			new_courses = connection.execute(
				"""SELECT id, name, category, content_type
				   FROM courses
				   ORDER BY id DESC
				   LIMIT 4"""
			).fetchall()
			
			latest_posts = connection.execute(
				"""SELECT p.id, p.title, p.category, p.views, u.full_name AS creator_name
				   FROM posts p
				   JOIN users u ON u.id = p.created_by
				   WHERE p.status = 'PUBLISHED'
				   ORDER BY p.id DESC
				   LIMIT 4"""
			).fetchall()
			
			available_courses = connection.execute(
				"""SELECT c.*, creator.full_name AS course_owner,
				   (SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS avg_rating,
				   (SELECT COUNT(*) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS rating_count
				   FROM courses c
				   LEFT JOIN users creator ON c.created_by = creator.id
				   WHERE c.status = 'published'
				     AND c.id NOT IN (SELECT course_id FROM course_assignments WHERE student_id = ?)
				     AND c.created_by != ?
				   ORDER BY c.id DESC""",
				(session.get("user_id", 0), session.get("user_id", 0))
			).fetchall()

		with get_db() as connection:
			if session.get("role") in ("admin", "moderator"):
				assessments = connection.execute("SELECT DISTINCT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id LEFT JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE c.created_by = ? OR ca.student_id IS NOT NULL ORDER BY a.id DESC", (session.get("user_id", 0), session.get("user_id", 0))).fetchall()
			else:
				assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE ca.status = 'completed' ORDER BY a.id DESC", (session.get("user_id", 0),)).fetchall()
			user_certifications = connection.execute("SELECT * FROM course_certifications WHERE user_id = ? AND certification_status = 'CERTIFIED' ORDER BY course_name", (session.get("user_id", 0),)).fetchall() if session.get("user_id") else []
		return render_template(
			"index.html", 
			user=session.get("user"), 
			role=session.get("role"), 
			actual_role=session.get("actual_role"), 
			profile_picture=session.get("profile_picture"), 
			impersonating=session.get("impersonator_id"), 
			courses=courses, 
			assessments=assessments, 
			user_certifications=user_certifications,
			leaderboard=leaderboard,
			new_courses=new_courses,
			latest_posts=latest_posts,
			available_courses=available_courses
		)


	@app.route("/groups", methods=["GET", "POST"])
	@staff_required
	def groups_page():
		"""Create groups and manage memberships for course assignment."""
		if request.method == "POST":
			if session.get("role") != "admin":
				flash("Only administrators can create groups.")
				return redirect(url_for("groups_page"))
			name = request.form.get("name", "").strip()
			description = request.form.get("description", "").strip()
			group_type = request.form.get("group_type", "").strip()
			status = request.form.get("status", "active").strip() or "active"
			if not name:
				flash("Group name is required.")
				return redirect(url_for("groups_page"))
			with get_db() as connection:
				cursor = connection.execute(
					"INSERT INTO groups (name, description, group_type, status, created_by) VALUES (?, ?, ?, ?, ?)",
					(name, description, group_type, status, session["user_id"])
				)
				selected = request.form.getlist("selected_users")
				for raw_user_id in selected:
					user_id = int(raw_user_id)
					connection.execute(
						"INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) SELECT ?, u.id, COALESCE(u.employee_id, ''), COALESCE(u.email, ''), COALESCE(u.department, ''), COALESCE(u.location, ''), CASE WHEN COALESCE(u.is_active, 1) = 1 THEN 'active' ELSE 'inactive' END FROM users u WHERE u.id = ?",
						(cursor.lastrowid, user_id)
				)
			flash("Group created successfully.")
			return redirect(url_for("groups_page"))
		with get_db() as connection:
			groups = connection.execute("""
				SELECT g.*, u.full_name AS creator_name,
				(SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) AS member_count,
				(SELECT COUNT(DISTINCT gca.course_id) FROM group_course_assignments gca WHERE gca.group_id = g.id) AS course_count
				FROM groups g
				JOIN users u ON u.id = g.created_by
				ORDER BY g.id DESC
			""").fetchall()
			users = connection.execute("SELECT id, full_name, username, role, employee_id, department, location, COALESCE(is_active, 1) AS is_active FROM users ORDER BY full_name").fetchall()
		return render_template("groups.html", groups=groups, users=users, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/groups/<int:group_id>")
	@staff_required
	def group_detail(group_id):
		"""Display group summary, members, and assigned courses."""
		with get_db() as connection:
			group = connection.execute("SELECT g.*, u.full_name AS creator_name FROM groups g JOIN users u ON u.id = g.created_by WHERE g.id = ?", (group_id,)).fetchone()
			if not group:
				flash("Group not found.")
				return redirect(url_for("groups_page"))
			members = connection.execute("""
				SELECT gm.*, u.full_name, u.username, u.role, u.email, u.department, u.location, COALESCE(u.is_active, 1) AS is_active
				FROM group_members gm
				JOIN users u ON u.id = gm.user_id
				WHERE gm.group_id = ?
				ORDER BY u.full_name
			""", (group_id,)).fetchall()
			assigned_courses = connection.execute("""
				SELECT gca.*, c.name AS course_name, c.created_by, u.full_name AS assigned_by_name,
				(SELECT COUNT(*) FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id WHERE ca.course_id = c.id AND gm.group_id = gca.group_id) AS member_access,
				(SELECT COUNT(*) FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id WHERE ca.course_id = c.id AND gm.group_id = gca.group_id AND ca.status = 'completed') AS completed_count,
				(SELECT COUNT(*) FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id WHERE ca.course_id = c.id AND gm.group_id = gca.group_id AND ca.status = 'assessment_failed') AS failed_count,
				(SELECT COUNT(DISTINCT cc.user_id) FROM course_certifications cc JOIN group_members gm ON gm.user_id = cc.user_id WHERE cc.course_id = c.id AND gm.group_id = gca.group_id AND cc.certification_status = 'CERTIFIED') AS certified_count
				FROM group_course_assignments gca
				JOIN courses c ON c.id = gca.course_id
				LEFT JOIN users u ON u.id = gca.assigned_by
				WHERE gca.group_id = ?
				ORDER BY gca.assigned_at DESC
			""", (group_id,)).fetchall()
			all_courses = connection.execute("SELECT id, name FROM courses ORDER BY name").fetchall()
			overall_progress = connection.execute("SELECT COUNT(*) AS total_access FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id WHERE gm.group_id = ?", (group_id,)).fetchone()["total_access"]
			certified_count = connection.execute("SELECT COUNT(DISTINCT cc.user_id) AS certified FROM course_certifications cc JOIN group_members gm ON gm.user_id = cc.user_id WHERE gm.group_id = ? AND cc.certification_status = 'CERTIFIED'", (group_id,)).fetchone()["certified"]
			user_count = len(members)
			course_count = len(assigned_courses)
		return render_template("group_detail.html", group=group, members=members, assigned_courses=assigned_courses, all_courses=all_courses, user_count=user_count, course_count=course_count, overall_progress=overall_progress, certified_count=certified_count, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/groups/<int:group_id>/members")
	@staff_required
	def add_group_members(group_id):
		"""Add selected users to an existing group."""
		if session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
		with get_db() as connection:
			group = connection.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
			if not group:
				flash("Group not found.")
				return redirect(url_for("groups_page"))
			for raw_user_id in request.form.getlist("selected_users"):
				user_id = int(raw_user_id)
				connection.execute(
					"INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) SELECT ?, u.id, COALESCE(u.employee_id, ''), COALESCE(u.email, ''), COALESCE(u.department, ''), COALESCE(u.location, ''), CASE WHEN COALESCE(u.is_active, 1) = 1 THEN 'active' ELSE 'inactive' END FROM users u WHERE u.id = ?",
					(group_id, user_id)
				)
		flash("Selected users added to the group.")
		return redirect(url_for("group_detail", group_id=group_id))

	@app.post("/groups/<int:group_id>/remove-member")
	@staff_required
	def remove_group_member(group_id):
		"""Remove a user from a group while leaving any existing course access intact."""
		user_id = request.form.get("user_id")
		if user_id:
			with get_db() as connection:
				connection.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, int(user_id)))
		flash("User removed from group. Existing course access remains unchanged.")
		return redirect(url_for("group_detail", group_id=group_id))

	@app.post("/groups/<int:group_id>/assign-course")
	@staff_required
	def assign_group_course(group_id):
		"""Assign a course to all members of a group with duplicate checks only on user/course access."""
		course_id = request.form.get("course_id")
		if not course_id:
			flash("Please choose a course to assign.")
			return redirect(url_for("group_detail", group_id=group_id))
		with get_db() as connection:
			group = connection.execute("SELECT g.*, u.full_name AS creator_name FROM groups g JOIN users u ON u.id = g.created_by WHERE g.id = ?", (group_id,)).fetchone()
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (int(course_id),)).fetchone()
			if not group or not course:
				flash("Group or course not found.")
				return redirect(url_for("groups_page"))
			existing = connection.execute("SELECT * FROM group_course_assignments WHERE group_id = ? AND course_id = ?", (group_id, int(course_id))).fetchone()
			if existing:
				flash("This course is already assigned to the group.")
				return redirect(url_for("group_detail", group_id=group_id))
			connection.execute("INSERT INTO group_course_assignments (group_id, course_id, assigned_by, status) VALUES (?, ?, ?, 'active')", (group_id, int(course_id), session["user_id"]))
			members = connection.execute("SELECT user_id FROM group_members WHERE group_id = ? ORDER BY user_id", (group_id,)).fetchall()
			for row in members:
				user_id = row["user_id"]
				if user_id == course["created_by"]:
					continue
				user = connection.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
				if user and not user_has_course_access(connection, user_id, int(course_id)):
					connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (int(course_id), user_id))
					create_group_assignment_history(connection, int(course_id), course["name"], user_id, user["full_name"], 'Group', group_id, group["name"], session["user_id"], session["user"], 'new', 'assigned')
				else:
					create_group_assignment_history(connection, int(course_id), course["name"], user_id, user["full_name"], 'Group', group_id, group["name"], session["user_id"], session["user"], 'Existing Access â€” No Action Taken', 'duplicate')
		flash("Course assigned to the group. Existing access was preserved for users who already had the course.")
		return redirect(url_for("group_detail", group_id=group_id))

	@app.post("/groups/upload-members")
	@staff_required
	def upload_group_members():
		"""Bulk upload members for a group using a simple CSV template."""
		group_id = request.form.get("group_id")
		file = request.files.get("members_file")
		if not group_id or not file or not file.filename:
			flash("Please select a group and a valid CSV upload.")
			return redirect(url_for("groups_page"))
		if not file.filename.lower().endswith(".csv"):
			flash("Please upload a CSV file.")
			return redirect(url_for("groups_page"))
		with get_db() as connection:
			reader = csv.DictReader(TextIOWrapper(file.stream, encoding="utf-8-sig"))
			seen = set()
			added = 0
			duplicates = 0
			invalid = 0
			for row in reader:
				employee_id = (row.get("Employee ID") or row.get("employee_id") or "").strip()
				username = (row.get("User Name") or row.get("user_name") or "").strip()
				email = (row.get("Email") or row.get("email") or "").strip()
				role = (row.get("User Role") or row.get("user_role") or "").strip()
				if not employee_id or not username or not email:
					invalid += 1
					continue
				if employee_id in seen:
					duplicates += 1
					continue
				seen.add(employee_id)
				user = connection.execute("SELECT * FROM users WHERE employee_id = ? OR username = ?", (employee_id, username)).fetchone()
				if not user:
					invalid += 1
					continue
				if user["is_active"] is not None and user["is_active"] == 0:
					invalid += 1
					continue
				connection.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) VALUES (?, ?, ?, ?, ?, ?, 'active')", (int(group_id), user["id"], user["employee_id"], user["email"], user["department"], user["location"]))
				added += 1
		flash(f"Bulk upload completed: {added} added, {duplicates} duplicates, {invalid} invalid rows.")
		return redirect(url_for("group_detail", group_id=int(group_id)))

	@app.get("/groups/template")
	@staff_required
	def download_group_template():
		"""Download a CSV template for bulk group member uploads."""
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(["Employee ID", "User Name", "Email", "User Role"])
		writer.writerow(["EMP-1001", "john.doe", "john.doe@company.com", "basic user"])
		output = stream.getvalue().encode("utf-8")
		return send_file(BytesIO(output), as_attachment=True, download_name="group_members_template.csv", mimetype="text/csv")

	
	
	@app.get("/api/notifications/unread")
	def api_get_unread_notifications():
		if "user_id" not in session:
			return jsonify({"count": 0, "notifications": []})
		with get_db() as conn:
			notifications = conn.execute(
				"SELECT id, message, type, target_url, created_at FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC", 
				(session["user_id"],)
			).fetchall()
		return jsonify({"count": len(notifications), "notifications": [dict(n) for n in notifications]})

	@app.post("/api/notifications/<int:notif_id>/read")
	def api_mark_notification_read(notif_id):
		if "user_id" not in session:
			return jsonify({"error": "Unauthorized"}), 401
		with get_db() as conn:
			conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notif_id, session["user_id"]))
		return jsonify({"success": True})

	@app.get("/admin/reports")
	@staff_required
	def admin_reports():
		"""Render the reporting and analytics dashboard."""
		with get_db() as connection:
			# User Stats
			total_users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
			active_users = connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
			
			# Course Stats
			total_courses = connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
			active_courses = connection.execute("SELECT COUNT(*) FROM courses WHERE status = 'published'").fetchone()[0]
			
			# Assessment Stats
			total_attempts = connection.execute("SELECT COUNT(*) FROM assessment_attempts").fetchone()[0]
			passed_attempts = connection.execute("SELECT COUNT(*) FROM assessment_attempts WHERE result = 'pass'").fetchone()[0]
			pass_rate = round((passed_attempts / total_attempts * 100) if total_attempts > 0 else 0, 1)
			
			# Rewards Stats
			total_points_issued = connection.execute("SELECT SUM(total_earned) FROM user_wallets").fetchone()[0] or 0
			
			# Chart Data: Completions by Category
			cat_data = connection.execute("""
				SELECT c.category, COUNT(cc.id) as completions 
				FROM courses c 
				LEFT JOIN course_certifications cc ON c.id = cc.course_id 
				GROUP BY c.category
			""").fetchall()
			categories = [row[0] for row in cat_data]
			completions = [row[1] for row in cat_data]
			
			# Leaderboard: Top Learners
			top_learners = connection.execute("""
				SELECT user_name, COUNT(*) as certs 
				FROM course_certifications 
				GROUP BY user_id, user_name 
				ORDER BY certs DESC 
				LIMIT 5
			""").fetchall()
			
			# Recent Activity
			recent_activity = connection.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 5").fetchall()
			
		return render_template("reports.html", 
			total_users=total_users, 
			active_users=active_users,
			total_courses=total_courses,
			active_courses=active_courses,
			total_attempts=total_attempts,
			pass_rate=pass_rate,
			total_points_issued=total_points_issued,
			chart_categories=categories,
			chart_completions=completions,
			top_learners=[dict(row) for row in top_learners],
			recent_activity=[dict(row) for row in recent_activity],
			user=session.get("user"), 
			role=session.get("role"),
			profile_picture=session.get("profile_picture")
		)


	@app.route("/admin", methods=["GET", "POST"])
	@staff_required
	def admin_panel():
		"""Create users, manage courses, and assign courses to individuals or groups."""
		if request.method == "POST":
			action = request.form.get("action")
			if action == "add_user" and session.get("role") == "admin":
				full_name = request.form.get("full_name", "").strip()
				username = request.form.get("username", "").strip().lower()
				password = request.form.get("password", "")
				role = request.form.get("role", "basic user")
				employee_id = request.form.get("employee_id", "").strip()
				department = request.form.get("department", "").strip()
				location = request.form.get("location", "").strip()
				if not full_name or not username or len(password) < 6 or role not in ROLES:
					flash("Enter all fields and use a password of at least 6 characters.")
				else:
					try:
						with get_db() as connection:
							connection.execute(
								"INSERT INTO users (full_name, username, password_hash, role, employee_id, department, location, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
								(full_name, username, generate_password_hash(password), role, employee_id, department, location),
							)
						flash("User added successfully.")
					except sqlite3.IntegrityError:
						flash("That username already exists.")
			elif action == "update_user" and session.get("role") == "admin":
				with get_db() as connection:
					connection.execute(
						"UPDATE users SET full_name = ?, username = ?, role = ? WHERE id = ? AND id != ?",
						(request.form["full_name"].strip(), request.form["username"].strip().lower(), request.form["role"], request.form["record_id"], session["user_id"]),
					)
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
						cursor = connection.execute(
							"INSERT INTO courses (name, description, category, content_type, content_url, created_by) VALUES (?, ?, ?, ?, ?, ?)",
							(name, description, category, content_type, content_url, session["user_id"]),
						)
						connection.execute("INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'create', 'course', ?)", (session["user_id"], cursor.lastrowid))
					flash("Course created successfully.")
			elif action == "update_course":
				with get_db() as connection:
					if course_is_manageable(connection, request.form["record_id"], session["user_id"], session["role"]):
						connection.execute(
							"UPDATE courses SET name = ?, description = ?, category = ?, status = ? WHERE id = ?",
							(request.form["name"].strip(), request.form.get("description", "").strip(), request.form.get("category", "General").strip(), request.form.get("status", "published"), request.form["record_id"]),
						)
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
						explanation = request.form.get("explanation", "").strip() or None
						question_id = connection.execute(
							"INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, created_by, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
							(bank[0], request.form["question_text"].strip(), request.form["option_a"].strip(), request.form["option_b"].strip(), request.form["option_c"].strip(), request.form["option_d"].strip(), request.form["correct_option"], int(request.form.get("marks", 1)), request.form.get("difficulty", "medium"), session["user_id"], explanation),
						).lastrowid
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
			elif action == "generate_api_creds":
				target_user_id = int(request.form["target_user_id"])
				import os
				api_key = "ak_" + os.urandom(16).hex()
				api_secret = "as_" + os.urandom(24).hex()
				with get_db() as connection:
					connection.execute("UPDATE api_credentials SET status = 'inactive' WHERE user_id = ?", (target_user_id,))
					connection.execute(
						"INSERT INTO api_credentials (user_id, api_key, api_secret, status) VALUES (?, ?, ?, 'active')",
						(target_user_id, api_key, api_secret)
					)
				flash("API credentials generated successfully.")
			elif action == "revoke_api_creds":
				target_user_id = int(request.form["target_user_id"])
				with get_db() as connection:
					connection.execute("UPDATE api_credentials SET status = 'inactive' WHERE user_id = ?", (target_user_id,))
				flash("API credentials revoked successfully.")
			elif action == "assign_course":
				try:
					with get_db() as connection:
						assignment_type = request.form.get("assignment_type", "individual")
						course_id = int(request.form["course_id"])
						course_row = connection.execute("SELECT name, created_by FROM courses WHERE id = ?", (course_id,)).fetchone()
						if course_row is None:
							flash("Select a valid course.")
							return redirect(url_for("admin_panel"))
						course_name = course_row["name"]
						if assignment_type == "group":
							group_id = int(request.form["group_id"])
							group = connection.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
							if not group:
								flash("Select a valid group.")
								return redirect(url_for("admin_panel"))
							members = connection.execute("SELECT user_id FROM group_members WHERE group_id = ? ORDER BY user_id", (group_id,)).fetchall()
							for member in members:
								user_id = member["user_id"]
								if user_id == course_row["created_by"]:
									continue
								user = connection.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
								if user and not user_has_course_access(connection, user_id, course_id):
									connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (course_id, user_id))
									connection.execute(
										"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) SELECT ?, c.name, u.id, u.full_name, 'Group', ?, g.name, ?, ?, 'assigned', 'new' FROM users u JOIN courses c ON c.id = ? JOIN groups g ON g.id = ? WHERE u.id = ?",
										(course_id, group_id, session["user_id"], session["user"], course_id, group_id, user_id),
									)
								else:
									if user:
										connection.execute(
											"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Group', ?, ?, ?, ?, 'duplicate', 'Existing Access â€” No Action Taken')",
											(course_id, course_name, user_id, user["full_name"], group_id, group["name"], session["user_id"], session["user"]),
										)
						else:
							user_id = int(request.form["student_id"])
							if user_id == course_row["created_by"]:
								flash("Cannot assign a course to its owner.")
								return redirect(url_for("admin_panel"))
							user = connection.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
							if user and not user_has_course_access(connection, user_id, course_id):
								connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (course_id, user_id))
								connection.execute(
									"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Individual', NULL, NULL, ?, ?, 'assigned', 'new')",
									(course_id, course_name, user_id, user["full_name"], session["user_id"], session["user"]),
								)
							else:
								if user:
									connection.execute(
										"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Individual', NULL, NULL, ?, ?, 'duplicate', 'Existing Access â€” No Action Taken')",
										(course_id, course_name, user_id, user["full_name"], session["user_id"], session["user"]),
									)
					flash("Course assignment processed. Existing course access was preserved when present.")
				except (sqlite3.IntegrityError, KeyError, ValueError):
					flash("That course assignment could not be completed.")

		with get_db() as connection:
			users = connection.execute("SELECT u.id, u.full_name, u.username, u.role, COALESCE(GROUP_CONCAT(ca.course_id), '') AS course_ids FROM users u LEFT JOIN course_assignments ca ON ca.student_id = u.id GROUP BY u.id ORDER BY u.id").fetchall()
			courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY c.id DESC", (session["user_id"], session["user_id"])).fetchall()
			students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user' ORDER BY full_name").fetchall()
			banks = connection.execute("SELECT * FROM question_banks ORDER BY id DESC").fetchall()
			assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY a.id DESC", (session["user_id"], session["user_id"])).fetchall()
			groups = connection.execute("SELECT * FROM groups ORDER BY id DESC").fetchall()
			api_creds = connection.execute("SELECT ac.*, u.username, u.full_name, u.role FROM api_credentials ac JOIN users u ON u.id = ac.user_id ORDER BY ac.id DESC").fetchall()
		return render_template("admin.html", users=users, courses=courses, students=students, banks=banks, assessments=assessments, groups=groups, api_creds=api_creds, content_types=CONTENT_TYPES, roles=ROLES, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.route("/assessments/<int:assessment_id>", methods=["GET", "POST"])
	def assessment(assessment_id):
		"""Display and grade a student's assessment while keeping failed attempts retryable."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			assessment_row = connection.execute(
				"SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id WHERE a.id = ?",
				(assessment_id,),
			).fetchone()
			questions = connection.execute(
				"SELECT q.* FROM questions q JOIN assessment_questions aq ON aq.question_id = q.id WHERE aq.assessment_id = ? ORDER BY q.id",
				(assessment_id,),
			).fetchall()
			if not assessment_row:
				return redirect(url_for("home"))
			allowed = connection.execute(
				"SELECT 1 FROM course_assignments WHERE student_id = ? AND course_id = ? LIMIT 1",
				(session["user_id"], assessment_row["course_id"]),
			).fetchone() is not None
			certification = get_user_course_record(connection, session["user_id"], assessment_row["course_id"])
			if not allowed:
				flash("Complete the course before starting the assessment.")
				return redirect(url_for("course_detail", course_id=assessment_row["course_id"]))
			if certification and certification["certification_status"] == "CERTIFIED":
				flash("This course is already certified. You can review the material and view your certificate, but you cannot retake the assessment.")
				return redirect(url_for("course_detail", course_id=assessment_row["course_id"]))
			if certification and certification["latest_assessment_status"] == "FEEDBACK_PENDING":
				return redirect(url_for("feedback_form", course_id=assessment_row["course_id"]))
			assignment = connection.execute(
				"SELECT status FROM course_assignments WHERE course_id = ? AND student_id = ?",
				(assessment_row["course_id"], session["user_id"]),
			).fetchone()
			is_completed = assignment and get_course_status_label(assignment["status"]) in ("ASSESSMENT_PENDING", "IN_PROGRESS", "ASSESSMENT_FAILED")
		if not is_completed:
			flash("Complete the course before starting the assessment.")
			return redirect(url_for("course_detail", course_id=assessment_row["course_id"]))
		if request.method == "POST":
			with get_db() as connection:
				cert_row = get_user_course_record(connection, session["user_id"], assessment_row["course_id"])
				if cert_row and cert_row["certification_status"] == "CERTIFIED":
					flash("This course is already certified.")
					return redirect(url_for("course_detail", course_id=assessment_row["course_id"]))
				attempt_count = connection.execute("SELECT COUNT(*) AS n FROM assessment_attempts WHERE assessment_id = ? AND student_id = ?", (assessment_id, session["user_id"])).fetchone()["n"]
				attempt = connection.execute("INSERT INTO assessment_attempts (assessment_id, student_id, attempt_no, status, result) VALUES (?, ?, ?, 'evaluated', 'fail')", (assessment_id, session["user_id"], attempt_count + 1))
				attempt_id = attempt.lastrowid
				score = 0
				for question in questions:
					selected = request.form.get(f"q{question['id']}")
					correct = selected == question["correct_option"]
					marks = question["marks"] if correct else 0
					score += marks
					connection.execute("INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) VALUES (?, ?, ?, ?, ?)", (attempt_id, question["id"], selected, correct, marks))
				percentage = (score / max(sum(q["marks"] for q in questions), 1)) * 100
				result = "pass" if percentage >= assessment_row["pass_percentage"] else "fail"
				connection.execute("UPDATE assessment_attempts SET score=?, percentage=?, result=?, submitted_at=CURRENT_TIMESTAMP, status='submitted' WHERE id=?", (score, percentage, result, attempt_id))
				course = connection.execute("SELECT c.name FROM courses c WHERE c.id = ?", (assessment_row["course_id"],)).fetchone()
				cert_row = get_user_course_record(connection, session["user_id"], assessment_row["course_id"])
				if cert_row is None:
					connection.execute(
						"INSERT INTO course_certifications (user_id, course_id, user_name, course_name, course_start_date, course_completion_date, assessment_score, pass_mark, assessment_attempts, latest_assessment_status, certification_status, badge) VALUES (?, ?, ?, ?, DATE('now'), DATE('now'), ?, ?, ?, ?, ?, ?)",
						(session["user_id"], assessment_row["course_id"], session["user"], course["name"], percentage, assessment_row["pass_percentage"], attempt_count + 1, "FEEDBACK_PENDING" if result == "pass" else "ASSESSMENT_FAILED", "FEEDBACK_PENDING" if result == "pass" else "ASSESSMENT_FAILED", "NOT CERTIFIED" if result == "fail" else "NOT CERTIFIED")
					)
				else:
					connection.execute(
						"UPDATE course_certifications SET user_name = ?, course_name = ?, assessment_score = ?, pass_mark = ?, assessment_attempts = ?, latest_assessment_status = ?, certification_status = ?, badge = ?, course_completion_date = COALESCE(course_completion_date, DATE('now')) WHERE user_id = ? AND course_id = ?",
						(session["user"], course["name"], percentage, assessment_row["pass_percentage"], attempt_count + 1, "FEEDBACK_PENDING" if result == "pass" else "ASSESSMENT_FAILED", "FEEDBACK_PENDING" if result == "pass" else "ASSESSMENT_FAILED", determine_badge(percentage, assessment_row["pass_percentage"]), session["user_id"], assessment_row["course_id"])
					)
				if result == "pass":
					connection.execute("UPDATE course_assignments SET status = 'feedback_pending', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?", (assessment_row["course_id"], session["user_id"]))
				else:
					connection.execute("UPDATE course_assignments SET status = 'assessment_failed', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?", (assessment_row["course_id"], session["user_id"]))
				return redirect(url_for("assessment_result", attempt_id=attempt_id))
		return render_template("assessment.html", assessment=assessment_row, questions=questions)

	@app.get("/assessment/result/<int:attempt_id>")
	def assessment_result(attempt_id):
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			attempt = connection.execute(
				"""SELECT a.*, ast.title, ast.pass_percentage, ast.id AS assessment_id, c.name AS course_name, c.id AS course_id
				   FROM assessment_attempts a
				   JOIN assessments ast ON ast.id = a.assessment_id
				   JOIN courses c ON c.id = ast.course_id
				   WHERE a.id = ?""",
				(attempt_id,)
			).fetchone()
			
			if not attempt:
				flash("Assessment attempt not found.")
				return redirect(url_for("home"))
				
			if attempt["student_id"] != session["user_id"]:
				flash("Unauthorized access to this assessment attempt.")
				return redirect(url_for("home"))
				
			total_questions = connection.execute(
				"SELECT COUNT(*) AS count FROM attempt_answers WHERE attempt_id = ?",
				(attempt_id,)
			).fetchone()["count"]
			
			correct_answers = connection.execute(
				"SELECT COUNT(*) AS count FROM attempt_answers WHERE attempt_id = ? AND is_correct = 1",
				(attempt_id,)
			).fetchone()["count"]
			
			incorrect_answers = total_questions - correct_answers
			
			total_marks = connection.execute(
				"""SELECT SUM(q.marks) AS total 
				   FROM questions q
				   JOIN assessment_questions aq ON aq.question_id = q.id
				   WHERE aq.assessment_id = ?""",
				(attempt["assessment_id"],)
			).fetchone()["total"] or 0
			
			marks_obtained = attempt["score"]
			
		return render_template(
			"assessment_result.html",
			attempt=attempt,
			total_questions=total_questions,
			correct_answers=correct_answers,
			incorrect_answers=incorrect_answers,
			total_marks=total_marks,
			marks_obtained=marks_obtained,
			user=session.get("user"),
			role=session.get("role"),
			actual_role=session.get("actual_role"),
			profile_picture=session.get("profile_picture")
		)

	@app.get("/assessment/review/<int:attempt_id>")
	def assessment_review(attempt_id):
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			attempt = connection.execute(
				"""SELECT a.*, ast.title, ast.id AS assessment_id, c.name AS course_name, c.id AS course_id
				   FROM assessment_attempts a
				   JOIN assessments ast ON ast.id = a.assessment_id
				   JOIN courses c ON c.id = ast.course_id
				   WHERE a.id = ?""",
				(attempt_id,)
			).fetchone()
			
			if not attempt:
				flash("Assessment attempt not found.")
				return redirect(url_for("home"))
				
			if attempt["student_id"] != session["user_id"]:
				flash("Unauthorized access to this assessment attempt.")
				return redirect(url_for("home"))
				
			if attempt["result"] != "pass":
				flash("Answer review is only available for passed assessments.")
				return redirect(url_for("course_detail", course_id=attempt["course_id"]))
				
			questions_reviews = connection.execute(
				"""SELECT q.*, aa.selected_option, aa.is_correct, aa.marks_awarded
				   FROM questions q
				   JOIN attempt_answers aa ON aa.question_id = q.id
				   WHERE aa.attempt_id = ?
				   ORDER BY q.id""",
				(attempt_id,)
			).fetchall()
			
		return render_template(
			"assessment_review.html",
			attempt=attempt,
			questions_reviews=questions_reviews,
			user=session.get("user"),
			role=session.get("role"),
			actual_role=session.get("actual_role"),
			profile_picture=session.get("profile_picture")
		)

	@app.get("/admin/reports")
	@admin_required
	def reports():
		"""Show a lightweight table-overview report for the LMS."""
		with get_db() as connection:
			tables = [row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
			report = [(table, connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]) for table in tables]
		return render_template("reports.html", report=report, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/course/<int:course_id>")
	def course_detail(course_id):
		"""Show assigned course content and each student's completion state."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			allowed = course_is_visible(connection, course_id, session["user_id"])
			assignment = connection.execute("SELECT status, completed_at FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"])).fetchone()
			if not assignment and course and course["status"] == 'published' and course["created_by"] != session["user_id"]:
				connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', NULL)", (course_id, session["user_id"]))
				connection.execute("INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Individual', ?, ?, 'assigned', 'new')", (course_id, course["name"], session["user_id"], session["user"], session["user_id"], "Self-Enrolled"))
				assignment = connection.execute("SELECT status, completed_at FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"])).fetchone()
			
			certification = get_user_course_record(connection, session["user_id"], course_id)
			progress = get_course_status_label(assignment["status"]) if assignment else "NOT_STARTED"
			if certification and certification["certification_status"] == "CERTIFIED":
				progress = "CERTIFIED"
			if certification and certification["latest_assessment_status"] == "FEEDBACK_PENDING":
				progress = "FEEDBACK_PENDING"
			assessments = connection.execute("SELECT * FROM assessments WHERE course_id = ? ORDER BY id", (course_id,)).fetchall()
		if not course or not allowed:
			return redirect(url_for("home"))
		return render_template("course.html", course=course, progress=progress, certification=certification, assessments=assessments, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"), impersonating=session.get("impersonator_id"))

	@app.post("/course/<int:course_id>/complete")
	def complete_course(course_id):
		"""Mark course as completed for the current student."""
		if not session.get("user_id") or session.get("role") != "basic user":
			return redirect(url_for("home"))
		with get_db() as connection:
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if certification and certification["certification_status"] == "CERTIFIED":
				flash("Course already certified; you can review the material and view the certificate.")
				return redirect(url_for("course_detail", course_id=course_id))
			connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status='in_progress', completed_at=COALESCE(course_assignments.completed_at, CURRENT_TIMESTAMP)", (course_id, session["user_id"]))
		return redirect(url_for("course_detail", course_id=course_id))

	@app.route("/course/<int:course_id>/feedback", methods=["GET", "POST"])
	def feedback_form(course_id):
		"""Collect mandatory feedback and issue the certificate if valid."""
		if not session.get("user_id") or session.get("role") != "basic user":
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course or not course_is_visible(connection, course_id, session["user_id"]):
				return redirect(url_for("home"))
			if certification and certification["certification_status"] == "CERTIFIED":
				return redirect(url_for("certificate", course_id=course_id))
			if not certification or certification["latest_assessment_status"] not in ("FEEDBACK_PENDING", "CERTIFIED"):
				return redirect(url_for("course_detail", course_id=course_id))
		if request.method == "POST":
			rating = request.form.get("rating", "").strip()
			comments = request.form.get("comments", "").strip()
			if not rating or not rating.isdigit() or not 1 <= int(rating) <= 10:
				flash("Overall rating is mandatory and must be between 1 and 10.")
				return redirect(url_for("feedback_form", course_id=course_id))
			if not comments:
				flash("Feedback comments are required before the certificate can be generated.")
				return redirect(url_for("feedback_form", course_id=course_id))
			with get_db() as connection:
				certification = get_user_course_record(connection, session["user_id"], course_id)
				if certification and certification["certification_status"] == "CERTIFIED":
					flash("A certificate has already been issued for this course.")
					return redirect(url_for("certificate", course_id=course_id))
				assessment = connection.execute(
					"SELECT COALESCE(MAX(percentage),0) AS latest_pct FROM assessment_attempts WHERE student_id = ? AND assessment_id IN (SELECT id FROM assessments WHERE course_id = ?)",
					(session["user_id"], course_id),
				).fetchone()
				final_score = float(assessment["latest_pct"]) if assessment else 0.0
				pass_mark = connection.execute("SELECT COALESCE(pass_percentage, 60) AS pass_mark FROM assessments WHERE course_id = ? ORDER BY id LIMIT 1", (course_id,)).fetchone()
				pass_mark = pass_mark["pass_mark"] if pass_mark else 60
				if final_score < pass_mark:
					flash("Certificate cannot be generated for a failed assessment.")
					return redirect(url_for("course_detail", course_id=course_id))
				certificate_id = f"CERT-{course_id}-{session['user_id']}-{os.urandom(4).hex().upper()}"
				badge = determine_badge(final_score, pass_mark)
				connection.execute(
					"INSERT INTO certificates (student_id, course_id, cert_uid, issued_date, file_url) VALUES (?, ?, ?, DATE('now'), ?) ON CONFLICT(cert_uid) DO NOTHING",
					(session["user_id"], course_id, certificate_id, "")
				)
				connection.execute(
					"INSERT INTO course_certifications (user_id, course_id, user_name, course_name, course_start_date, course_completion_date, assessment_score, pass_mark, assessment_attempts, latest_assessment_status, feedback_rating, feedback_comments, feedback_submitted_at, certificate_id, certificate_generated_at, badge, certification_status) VALUES (?, ?, ?, ?, DATE('now'), DATE('now'), ?, ?, (SELECT COUNT(*) FROM assessment_attempts WHERE student_id = ? AND assessment_id IN (SELECT id FROM assessments WHERE course_id = ?)), 'CERTIFIED', ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP, ?, 'CERTIFIED') ON CONFLICT(user_id, course_id) DO UPDATE SET user_name = excluded.user_name, course_name = excluded.course_name, assessment_score = excluded.assessment_score, pass_mark = excluded.pass_mark, assessment_attempts = excluded.assessment_attempts, latest_assessment_status = 'CERTIFIED', feedback_rating = excluded.feedback_rating, feedback_comments = excluded.feedback_comments, feedback_submitted_at = CURRENT_TIMESTAMP, certificate_id = excluded.certificate_id, certificate_generated_at = CURRENT_TIMESTAMP, badge = excluded.badge, certification_status = 'CERTIFIED'",
					(session["user_id"], course_id, session["user"], course["name"], final_score, pass_mark, session["user_id"], course_id, int(rating), comments, certificate_id, badge)
				)
				connection.execute("UPDATE course_assignments SET status='certified', completed_at=COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"]))
				
				# Reward Engine integration
				score_row = connection.execute(
					"SELECT COALESCE(MAX(score), 0) AS max_score FROM assessment_attempts WHERE student_id = ? AND assessment_id IN (SELECT id FROM assessments WHERE course_id = ?)",
					(session["user_id"], course_id)
				).fetchone()
				attempt_score = score_row["max_score"] if score_row else 0
				
				# 1. Course Certification Reward
				process_reward_event(
					connection=connection,
					user_id=session["user_id"],
					event_name="COURSE_CERTIFICATION",
					source_reference_id=certificate_id,
					source_reference_type="CERTIFICATE",
					description=f"Course Certification - {course['name']} (Score: {attempt_score})",
					input_value=attempt_score,
					actor_id=session["user_id"]
				)
				
				# 2. Course Owner Rating Reward & 3. Rating Giver Reward
				ref_id = f"CRATE-{course_id}-{session['user_id']}"
				process_reward_event(
					connection=connection,
					user_id=course["created_by"],
					event_name="COURSE_OWNER_RATING",
					source_reference_id=ref_id,
					source_reference_type="COURSE_RATING",
					description=f"Course Rating received - {course['name']} (Rating: {rating}/10)",
					input_value=int(rating),
					actor_id=session["user_id"]
				)
				process_reward_event(
					connection=connection,
					user_id=session["user_id"],
					event_name="RATING_GIVEN",
					source_reference_id=ref_id,
					source_reference_type="COURSE_RATING",
					description=f"Rated course - {course['name']}",
					actor_id=session["user_id"]
				)
			flash("Feedback submitted successfully. Your certificate and badge have been created.")
			return redirect(url_for("certificate", course_id=course_id))
		return render_template("feedback.html", course=course, user=session.get("user"), certification=certification)

	@app.get("/course/<int:course_id>/certificate")
	def certificate(course_id):
		"""Display and allow a student to review or download their certificate."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course or not course_is_visible(connection, course_id, session["user_id"]):
				return redirect(url_for("home"))
			if not certification or certification["certification_status"] != "CERTIFIED":
				flash("Certificate is not available until feedback is submitted and the course is certified.")
				return redirect(url_for("course_detail", course_id=course_id))
		return render_template("certificate.html", course=course, certification=certification, user=session.get("user"))

	@app.get("/course/<int:course_id>/certificate/download")
	def download_certificate(course_id):
		"""Return the certificate as a downloadable PNG image for the student."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course or not course_is_visible(connection, course_id, session["user_id"]):
				return redirect(url_for("home"))
			if not certification or certification["certification_status"] != "CERTIFIED":
				flash("Certificate is not available until feedback is submitted and the course is certified.")
				return redirect(url_for("course_detail", course_id=course_id))
		response = render_template("certificate.html", course=course, certification=certification, user=session.get("user"), download_mode=True)
		return response


	@app.get("/admin/question-template")
	@staff_required
	def download_question_template():
		"""Download the Excel question and assessment template."""
		return send_file(question_template(), as_attachment=True, download_name="learnly_questions_template.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


	@app.get("/admin/api-credentials/<int:user_id>/download")
	@admin_required
	def download_api_credentials(user_id):
		"""Download the API Key and Secret for a specific user as a JSON file."""
		with get_db() as connection:
			creds = connection.execute(
				"SELECT ac.*, u.username, u.full_name FROM api_credentials ac JOIN users u ON u.id = ac.user_id WHERE ac.user_id = ? AND ac.status = 'active'",
				(user_id,)
			).fetchone()
			if not creds:
				flash("No active API credentials found for this user.")
				return redirect(url_for("admin_panel"))
				
			import json
			output = {
				"username": creds["username"],
				"full_name": creds["full_name"],
				"api_key": creds["api_key"],
				"api_secret": creds["api_secret"],
				"api_base_url": request.url_root.rstrip("/") + "/api/v1",
				"status": creds["status"]
			}
			return send_file(
				BytesIO(json.dumps(output, indent=4).encode("utf-8")),
				as_attachment=True,
				download_name=f"api_credentials_{creds['username']}.json",
				mimetype="application/json"
			)

	@app.post("/admin/delete/<resource>/<int:record_id>")
	@staff_required
	def delete_record(resource, record_id):
		"""Delete an approved staff/admin resource and report dependency conflicts."""
		allowed = {"user": "users", "course": "courses", "module": "modules", "assessment": "assessments"}
		table = allowed.get(resource)
		if not table or resource == "user" and record_id == session.get("user_id"):
			flash("This record cannot be deleted.")
			return redirect(request.referrer or url_for("admin_panel"))

		with get_db() as connection:
			if resource == "course":
				course = connection.execute("SELECT created_by, status FROM courses WHERE id = ?", (record_id,)).fetchone()
				if not course:
					flash("Course not found.")
					return redirect(request.referrer or url_for("courses_page"))
				if session.get("role") != "admin" and course["created_by"] != session.get("user_id"):
					flash("You can only delete courses you created.")
					return redirect(request.referrer or url_for("courses_page"))
				if course["status"] != "draft":
					flash(f"Cannot delete a {course['status']} course. You can only delete draft courses.")
					return redirect(request.referrer or url_for("courses_page"))
			elif resource == "user" and session.get("role") != "admin":
				flash("You do not have permission to delete users.")
				return redirect(request.referrer or url_for("admin_panel"))

		try:
			with get_db() as connection:
				cursor = connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
				if cursor.rowcount:
					flash(f"{resource.title()} deleted successfully.")
				else:
					flash("Record not found.")
		except sqlite3.IntegrityError:
			flash("This record is still in use and cannot be deleted.")
		return redirect(request.referrer or url_for("admin_panel"))

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
				"""SELECT c.*, u.full_name AS creator_name,
				   (SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS avg_rating,
				   (SELECT COUNT(*) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS rating_count
				   FROM courses c JOIN users u ON u.id = c.created_by ORDER BY c.id DESC"""
			).fetchall()
		return render_template("courses.html",
			courses=courses,
			content_types=CONTENT_TYPES,
			user=session.get("user"),
			user_id=session.get("user_id"),
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
		source_type = request.form.get("source_type", "url")

		errors = []
		if not name:
			errors.append("Course title is required.")
		if len(name) > 200:
			errors.append("Course title must be under 200 characters.")

		content_url = None
		content_type = "URL"

		if source_type == "file":
			try:
				content_url = content_location("course_file")
				if content_url:
					content_type = detect_content_type(content_url)
			except ValueError:
				content_url = None
		else:
			content_url = request.form.get("content_url", "").strip()
			if content_url:
				content_type = detect_content_type(content_url)

		is_draft = (status == "draft")
		if not content_url:
			if is_draft:
				content_url = "#"
				content_type = "URL"
			else:
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
			
			# Get existing course to check current content
			existing = connection.execute("SELECT content_url, content_type FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not existing:
				flash("Course not found.")
				return redirect(url_for("courses_page"))

			source_type = request.form.get("source_type", "url")
			status = request.form.get("status", "draft")

			new_url = None
			content_type = existing["content_type"]

			if source_type == "url":
				new_url = request.form.get("content_url", "").strip()
				if new_url:
					content_type = detect_content_type(new_url)
			else:
				# Check if new file uploaded
				try:
					new_url = content_location("course_file")
					if new_url:
						content_type = detect_content_type(new_url)
				except ValueError:
					new_url = None
				
				# Keep existing URL if file unchanged
				if not new_url and existing["content_url"].startswith("/uploads/"):
					new_url = existing["content_url"]
					content_type = existing["content_type"]

			# Skip content checks for drafts, but require them for published courses
			is_draft = (status == "draft")
			if not new_url:
				if is_draft:
					new_url = existing["content_url"] or "#"
					content_type = existing["content_type"] or "URL"
				else:
					flash("Please provide a valid URL or file for publication.")
					return redirect(url_for("courses_page"))

			connection.execute(
				"UPDATE courses SET name=?, description=?, category=?, status=?, tags=?, duration_minutes=?, difficulty=?, thumbnail_color=?, content_type=?, content_url=? WHERE id=?",
				(
					request.form.get("name", "").strip(),
					request.form.get("description", "").strip(),
					request.form.get("category", "General").strip() or "General",
					status,
					request.form.get("tags", "").strip(),
					int(request.form.get("duration_minutes", 0) or 0),
					request.form.get("difficulty", "beginner"),
					request.form.get("thumbnail_color", "#6366f1"),
					content_type,
					new_url,
					course_id
				)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'update', 'course', ?)",
				(session["user_id"], course_id)
			)
		flash("Course updated.")
		return redirect(url_for("courses_page"))

	@app.post("/courses/<int:course_id>/publish")
	@staff_required
	def courses_publish(course_id):
		"""Quick publish a course."""
		with get_db() as connection:
			if not course_is_manageable(connection, course_id, session["user_id"], session["role"]):
				flash("You can only publish courses you created.")
				return redirect(url_for("courses_page"))
			
			course = connection.execute("SELECT content_url, content_type FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not course or course["content_url"] == "#" or not course["content_url"]:
				flash("Please upload educational material or add a URL before publishing this course.")
				return redirect(url_for("courses_page"))

			connection.execute("UPDATE courses SET status = 'published' WHERE id = ?", (course_id,))
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'publish', 'course', ?)",
				(session["user_id"], course_id)
			)
		flash("Course published successfully!")
		return redirect(url_for("courses_page"))


	@app.get("/view-as")
	@admin_required
	def view_as_page():
		with get_db() as connection:
			students = connection.execute("SELECT id, full_name, username, role FROM users WHERE id != ? ORDER BY full_name", (session["user_id"],)).fetchall()
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

	@app.context_processor
	def inject_notifications():
		if session.get("user_id"):
			try:
				with get_db() as connection:
					count = connection.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (session["user_id"],)).fetchone()["n"]
					return {"unread_notifications_count": count}
			except Exception:
				pass
		return {"unread_notifications_count": 0}

	def create_notification(connection, user_id, message, type_name="system"):
		connection.execute(
			"INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
			(user_id, message, type_name)
		)

	@app.get("/notifications")
	def notifications_page():
		if "user_id" not in session:
			return redirect(url_for("home"))
		with get_db() as connection:
			notifications = connection.execute(
				"SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC",
				(session["user_id"],)
			).fetchall()
		return render_template("notifications.html", notifications=notifications, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/notifications/read/<int:notif_id>")
	def mark_read(notif_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
		with get_db() as connection:
			connection.execute(
				"UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
				(notif_id, session["user_id"])
			)
		return redirect(url_for("notifications_page"))

	@app.post("/notifications/read-all")
	def mark_all_read():
		if "user_id" not in session:
			return redirect(url_for("home"))
		with get_db() as connection:
			connection.execute(
				"UPDATE notifications SET is_read = 1 WHERE user_id = ?",
				(session["user_id"],)
			)
		return redirect(url_for("notifications_page"))

	@app.route("/community/create", methods=["GET", "POST"])
	def create_post():
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		role = session.get("role")
		user_id = session.get("user_id")
		
		if request.method == "POST":
			title = request.form.get("title", "").strip()
			description = request.form.get("description", "").strip()
			content_type = request.form.get("content_type", "Text/Article")
			category = request.form.get("category", "General").strip() or "General"
			topic_tag = request.form.get("topic_tag", "").strip()
			status_input = request.form.get("status", "DRAFT")
			
			if role in ("admin", "moderator"):
				status = "PUBLISHED" if status_input != "DRAFT" else "DRAFT"
			else:
				status = "PENDING_APPROVAL" if status_input != "DRAFT" else "DRAFT"
				
			thumbnail_filename = None
			thumbnail_file = request.files.get("thumbnail")
			if thumbnail_file and thumbnail_file.filename:
				ext = os.path.splitext(thumbnail_file.filename)[1].lower()
				if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
					thumbnail_filename = f"thumb_{uuid4().hex}{ext}"
					thumbnail_file.save(UPLOAD_FOLDER / thumbnail_filename)
					
			with get_db() as connection:
				cursor = connection.execute(
					"""INSERT INTO posts (title, description, content_type, category, topic_tag, created_by, status, thumbnail, version_number)
					   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
					(title, description, content_type, category, topic_tag, user_id, status, thumbnail_filename)
				)
				post_id = cursor.lastrowid
				
				attachments = request.files.getlist("attachments")
				for file in attachments:
					if file and file.filename:
						ext = os.path.splitext(file.filename)[1].lower()
						file_name = secure_filename(file.filename)
						file_path = f"post_{post_id}_{uuid4().hex[:8]}_{file_name}"
						file.save(UPLOAD_FOLDER / file_path)
						
						file_size = os.path.getsize(UPLOAD_FOLDER / file_path)
						file_type = file.mimetype
						
						connection.execute(
							"""INSERT INTO post_attachments (post_id, file_name, file_type, file_path, file_size, uploaded_by)
							   VALUES (?, ?, ?, ?, ?, ?)""",
							(post_id, file.filename, file_type, file_path, file_size, user_id)
						)
						
				connection.execute(
					"""INSERT INTO post_approval_history (post_id, version_number, submitted_by, action, comments, previous_status, new_status)
					   VALUES (?, 1, ?, ?, ?, 'NONE', ?)""",
					(post_id, user_id, 'SUBMIT', 'Initial creation', status)
				)
				
				if status == "PENDING_APPROVAL":
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"New content '{title}' is waiting for approval.", "pending_review")
						
			flash("Post created successfully!")
			return redirect(url_for("my_posts"))
			
		return render_template("create_post.html", role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.route("/community/edit/<int:post_id>", methods=["GET", "POST"])
	def edit_post(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		role = session.get("role")
		
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			
		if not post:
			flash("Post not found.")
			return redirect(url_for("my_posts"))
			
		if post["created_by"] != user_id and role != "admin":
			flash("Unauthorized to edit this post.")
			return redirect(url_for("my_posts"))
			
		with get_db() as connection:
			attachments = connection.execute("SELECT * FROM post_attachments WHERE post_id = ?", (post_id,)).fetchall()
			
		if request.method == "POST":
			title = request.form.get("title", "").strip()
			description = request.form.get("description", "").strip()
			content_type = request.form.get("content_type", "Text/Article")
			category = request.form.get("category", "General").strip() or "General"
			topic_tag = request.form.get("topic_tag", "").strip()
			status_input = request.form.get("status", "DRAFT")
			
			delete_thumbnail = request.form.get("delete_thumbnail") == "1"
			delete_attachment_ids = request.form.getlist("delete_attachment")
			
			old_status = post["status"]
			
			if role in ("admin", "moderator"):
				new_status = "PUBLISHED" if status_input != "DRAFT" else "DRAFT"
			else:
				if old_status == "PUBLISHED" and status_input != "DRAFT":
					new_status = "PENDING_APPROVAL"
				elif status_input == "DRAFT":
					new_status = "DRAFT"
				else:
					new_status = "PENDING_APPROVAL"
					
			new_version = post["version_number"]
			if old_status == "PUBLISHED" or status_input != "DRAFT":
				new_version += 1
				
			with get_db() as connection:
				thumbnail_filename = post["thumbnail"]
				if delete_thumbnail and thumbnail_filename:
					try:
						(UPLOAD_FOLDER / thumbnail_filename).unlink(missing_ok=True)
					except Exception:
						pass
					thumbnail_filename = None
					
				thumbnail_file = request.files.get("thumbnail")
				if thumbnail_file and thumbnail_file.filename:
					if thumbnail_filename:
						try:
							(UPLOAD_FOLDER / thumbnail_filename).unlink(missing_ok=True)
						except Exception:
							pass
					ext = os.path.splitext(thumbnail_file.filename)[1].lower()
					if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
						thumbnail_filename = f"thumb_{uuid4().hex}{ext}"
						thumbnail_file.save(UPLOAD_FOLDER / thumbnail_filename)
						
				connection.execute(
					"""UPDATE posts 
					   SET title = ?, description = ?, content_type = ?, category = ?, topic_tag = ?, status = ?, thumbnail = ?, version_number = ?, updated_at = CURRENT_TIMESTAMP
					   WHERE id = ?""",
					(title, description, content_type, category, topic_tag, new_status, thumbnail_filename, new_version, post_id)
				)
				
				for att_id in delete_attachment_ids:
					att_row = connection.execute("SELECT file_path FROM post_attachments WHERE id = ? AND post_id = ?", (att_id, post_id)).fetchone()
					if att_row:
						try:
							(UPLOAD_FOLDER / att_row["file_path"]).unlink(missing_ok=True)
						except Exception:
							pass
						connection.execute("DELETE FROM post_attachments WHERE id = ?", (att_id,))
						
				new_attachments = request.files.getlist("attachments")
				for file in new_attachments:
					if file and file.filename:
						ext = os.path.splitext(file.filename)[1].lower()
						file_name = secure_filename(file.filename)
						file_path = f"post_{post_id}_{uuid4().hex[:8]}_{file_name}"
						file.save(UPLOAD_FOLDER / file_path)
						
						file_size = os.path.getsize(UPLOAD_FOLDER / file_path)
						file_type = file.mimetype
						
						connection.execute(
							"""INSERT INTO post_attachments (post_id, file_name, file_type, file_path, file_size, uploaded_by)
							   VALUES (?, ?, ?, ?, ?, ?)""",
							(post_id, file.filename, file_type, file_path, file_size, user_id)
						)
						
				action_type = "SUBMIT"
				change_desc = f"Updated post. Version incremented to {new_version}."
				if old_status == "PUBLISHED" and new_status == "PENDING_APPROVAL":
					change_desc = f"Student edited published post. Reverted to Pending Approval."
					
				connection.execute(
					"""INSERT INTO post_approval_history (post_id, version_number, submitted_by, action, comments, previous_status, new_status)
					   VALUES (?, ?, ?, ?, ?, ?, ?)""",
					(post_id, new_version, user_id, action_type, change_desc, old_status, new_status)
				)
				
				if old_status == "PUBLISHED" and new_status == "PENDING_APPROVAL":
					create_notification(connection, user_id, f"Your post '{title}' requires approval after modification.", "re_approval_needed")
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"Modified post '{title}' (previously published) is waiting for approval.", "pending_review")
				elif new_status == "PENDING_APPROVAL" and old_status != "PENDING_APPROVAL":
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"Post '{title}' is waiting for approval.", "pending_review")
						
			flash("Post updated successfully!")
			return redirect(url_for("my_posts"))
			
		return render_template("edit_post.html", post=post, attachments=attachments, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/community/my-posts")
	def my_posts():
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		role = session.get("role")
		
		with get_db() as connection:
			posts = connection.execute(
				"""SELECT p.*, 
						  (SELECT ROUND(AVG(r.rating), 1) FROM post_ratings r WHERE r.post_id = p.id) AS avg_rating,
						  (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.id) AS comment_count
				   FROM posts p
				   WHERE p.created_by = ?
				   ORDER BY p.id DESC""",
				(user_id,)
			).fetchall()
			
		return render_template("my_posts.html", posts=posts, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/community/delete/<int:post_id>")
	def delete_post(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		role = session.get("role")
		
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			
		if not post:
			flash("Post not found.")
			return redirect(url_for("my_posts"))
			
		is_owner = post["created_by"] == user_id
		if role == "basic user":
			if not is_owner or post["status"] not in ("DRAFT", "REJECTED"):
				flash("You can only delete your own draft or rejected posts.")
				return redirect(url_for("my_posts"))
		elif role != "admin" and not is_owner:
			flash("Unauthorized to delete this post.")
			return redirect(url_for("my_posts"))
			
		with get_db() as connection:
			atts = connection.execute("SELECT file_path FROM post_attachments WHERE post_id = ?", (post_id,)).fetchall()
			for att in atts:
				try:
					(UPLOAD_FOLDER / att["file_path"]).unlink(missing_ok=True)
				except Exception:
					pass
					
			if post["thumbnail"]:
				try:
					(UPLOAD_FOLDER / post["thumbnail"]).unlink(missing_ok=True)
				except Exception:
					pass
					
			connection.execute("DELETE FROM post_attachments WHERE post_id = ?", (post_id,))
			connection.execute("DELETE FROM post_ratings WHERE post_id = ?", (post_id,))
			connection.execute("DELETE FROM post_comments WHERE post_id = ?", (post_id,))
			connection.execute("DELETE FROM post_approval_history WHERE post_id = ?", (post_id,))
			connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
			
		flash("Post deleted successfully.")
		return redirect(url_for("my_posts"))

	@app.get("/community/approval-queue")
	def approval_queue():
		if "user_id" not in session or session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
			
		role = session.get("role")
		
		with get_db() as connection:
			posts = connection.execute(
				"""SELECT p.*, u.full_name AS creator_name, u.username
				   FROM posts p
				   JOIN users u ON u.id = p.created_by
				   WHERE p.status IN ('PENDING_APPROVAL', 'UNPUBLISHED')
				   ORDER BY p.id ASC"""
			).fetchall()
			
			pending_posts = []
			for p in posts:
				p_dict = dict(p)
				p_dict["attachments"] = connection.execute(
					"SELECT * FROM post_attachments WHERE post_id = ?",
					(p["id"],)
				).fetchall()
				pending_posts.append(p_dict)
				
		return render_template("approval_queue.html", pending_posts=pending_posts, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/community/approval-queue/<int:post_id>/action")
	def approval_action(post_id):
		if "user_id" not in session or session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
			
		reviewer_id = session.get("user_id")
		action = request.form.get("action")
		comments = request.form.get("comments", "").strip()
		
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			
		if not post:
			flash("Post not found.")
			return redirect(url_for("approval_queue"))
			
		old_status = post["status"]
		
		if action == "APPROVE":
			new_status = "PUBLISHED"
			audit_action = "APPROVE"
			notif_message = f"Your content '{post['title']}' has been approved and published."
			notif_type = "approval"
			published_by = reviewer_id
		elif action == "REJECT":
			new_status = "REJECTED"
			audit_action = "REJECT"
			notif_message = f"Your content '{post['title']}' was rejected. Reason: {comments}"
			notif_type = "rejection"
			published_by = None
		elif action == "REQUEST_CHANGES":
			new_status = "UNPUBLISHED"
			audit_action = "REQUEST_CHANGES"
			notif_message = f"Changes were requested for your content '{post['title']}': {comments}"
			notif_type = "change_request"
			published_by = None
		else:
			flash("Invalid action.")
			return redirect(url_for("approval_queue"))
			
		with get_db() as connection:
			if action == "APPROVE":
				connection.execute(
					"""UPDATE posts 
					   SET status = ?, published_by = ?, published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
					   WHERE id = ?""",
					(new_status, published_by, post_id)
				)
			else:
				connection.execute(
					"""UPDATE posts 
					   SET status = ?, updated_at = CURRENT_TIMESTAMP
					   WHERE id = ?""",
					(new_status, post_id)
				)
				
			connection.execute(
				"""INSERT INTO post_approval_history (post_id, version_number, submitted_by, reviewed_by, reviewed_at, action, comments, previous_status, new_status)
				   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)""",
				(post_id, post["version_number"], post["created_by"], reviewer_id, audit_action, comments, old_status, new_status)
			)
			
			create_notification(connection, post["created_by"], notif_message, notif_type)
			
		flash(f"Decision '{action}' submitted successfully!")
		return redirect(url_for("approval_queue"))

	@app.get("/community")
	def community_feed():
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		role = session.get("role")
		user_id = session.get("user_id")
		
		q = request.args.get("q", "").strip()
		category = request.args.get("category", "").strip()
		content_type = request.args.get("type", "").strip()
		sort = request.args.get("sort", "newest")
		
		sql = """
			SELECT p.*, u.full_name AS creator_name, u.role,
				   (SELECT ROUND(AVG(r.rating), 1) FROM post_ratings r WHERE r.post_id = p.id) AS avg_rating,
				   (SELECT COUNT(*) FROM post_ratings r WHERE r.post_id = p.id) AS rating_count,
				   (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.id) AS comment_count
			FROM posts p
			JOIN users u ON u.id = p.created_by
			WHERE p.status = 'PUBLISHED'
		"""
		params = []
		
		if q:
			sql += " AND (p.title LIKE ? OR p.description LIKE ? OR p.topic_tag LIKE ?)"
			params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
		if category:
			sql += " AND p.category = ?"
			params.append(category)
		if content_type:
			sql += " AND p.content_type = ?"
			params.append(content_type)
			
		if sort == "highest_rated":
			sql += " ORDER BY avg_rating DESC, p.id DESC"
		else:
			sql += " ORDER BY p.id DESC"
			
		with get_db() as connection:
			posts_rows = connection.execute(sql, params).fetchall()
			
			categories_rows = connection.execute("SELECT DISTINCT category FROM posts WHERE status = 'PUBLISHED' AND category != ''").fetchall()
			categories = [row["category"] for row in categories_rows]
			
			posts = []
			for p in posts_rows:
				p_dict = dict(p)
				p_dict["attachments"] = connection.execute("SELECT * FROM post_attachments WHERE post_id = ?", (p["id"],)).fetchall()
				posts.append(p_dict)
				
		return render_template("community_feed.html", posts=posts, categories=categories, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/community/post/<int:post_id>")
	def post_detail(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		role = session.get("role")
		
		with get_db() as connection:
			post = connection.execute(
				"""SELECT p.*, u.full_name AS creator_name, u.role,
						  (SELECT ROUND(AVG(r.rating), 1) FROM post_ratings r WHERE r.post_id = p.id) AS avg_rating,
						  (SELECT COUNT(*) FROM post_ratings r WHERE r.post_id = p.id) AS rating_count
				   FROM posts p
				   JOIN users u ON u.id = p.created_by
				   WHERE p.id = ?""",
				(post_id,)
			).fetchone()
			
		if not post:
			flash("Post not found.")
			return redirect(url_for("community_feed"))
			
		is_creator = post["created_by"] == user_id
		is_reviewer = role in ("admin", "moderator")
		if post["status"] != "PUBLISHED" and not (is_creator or is_reviewer):
			flash("Unauthorized to view this post.")
			return redirect(url_for("community_feed"))
			
		with get_db() as connection:
			connection.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (post_id,))
			
			attachments = connection.execute("SELECT * FROM post_attachments WHERE post_id = ?", (post_id,)).fetchall()
			
			user_rating = connection.execute("SELECT * FROM post_ratings WHERE post_id = ? AND user_id = ?", (post_id, user_id)).fetchone()
			
			comments = connection.execute(
				"""SELECT c.*, u.full_name, u.role, r.rating
				   FROM post_comments c
				   JOIN users u ON u.id = c.user_id
				   LEFT JOIN post_ratings r ON r.post_id = c.post_id AND r.user_id = c.user_id
				   WHERE c.post_id = ? AND c.status = 'active'
				   ORDER BY c.id DESC""",
				(post_id,)
			).fetchall()
			
		return render_template("post_detail.html", post=post, attachments=attachments, user_rating=user_rating, comments=comments, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/community/post/<int:post_id>/rate")
	def rate_post(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		try:
			rating = int(request.form.get("rating", 0))
		except ValueError:
			rating = 0
			
		if rating < 1 or rating > 5:
			flash("Invalid rating. Must be between 1 and 5.")
			return redirect(url_for("post_detail", post_id=post_id))
			
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				flash("Post not found.")
				return redirect(url_for("community_feed"))
				
			role = session.get("role")
			if post["status"] != "PUBLISHED" and not (post["created_by"] == user_id or role in ("admin", "moderator")):
				flash("Unauthorized to rate this post.")
				return redirect(url_for("community_feed"))
				
			connection.execute(
				"""INSERT INTO post_ratings (post_id, user_id, rating, updated_at)
				   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
				   ON CONFLICT(post_id, user_id) DO UPDATE SET rating = excluded.rating, updated_at = CURRENT_TIMESTAMP""",
				(post_id, user_id, rating)
			)
			
			# Reward Engine Integration
			ref_id = f"PRATE-{post_id}-{user_id}"
			
			# 1. Post Owner Reward
			process_reward_event(
				connection=connection,
				user_id=post["created_by"],
				event_name="COMMUNITY_POST_RATING",
				source_reference_id=ref_id,
				source_reference_type="POST_RATING",
				description=f"Community Post Rating received (Post ID: {post_id}, Rating: {rating}/5)",
				input_value=rating,
				actor_id=user_id
			)
			
			# 2. Rating Giver Reward
			process_reward_event(
				connection=connection,
				user_id=user_id,
				event_name="RATING_GIVEN",
				source_reference_id=ref_id,
				source_reference_type="POST_RATING",
				description=f"Rated community post (Post ID: {post_id})",
				actor_id=user_id
			)
			
		flash("Thank you for your rating!")
		return redirect(url_for("post_detail", post_id=post_id))

	@app.post("/community/post/<int:post_id>/comment")
	def comment_post(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		comment_text = request.form.get("comment_text", "").strip()
		
		if not comment_text:
			flash("Comment cannot be empty.")
			return redirect(url_for("post_detail", post_id=post_id))
			
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				flash("Post not found.")
				return redirect(url_for("community_feed"))
				
			role = session.get("role")
			if post["status"] != "PUBLISHED" and not (post["created_by"] == user_id or role in ("admin", "moderator")):
				flash("Unauthorized to comment on this post.")
				return redirect(url_for("community_feed"))
				
			connection.execute(
				"""INSERT INTO post_comments (post_id, user_id, comment_text)
				   VALUES (?, ?, ?)""",
				(post_id, user_id, comment_text)
			)
			
		flash("Comment submitted successfully!")
		return redirect(url_for("post_detail", post_id=post_id))

	@app.get("/admin/reports/content-master/download")
	@admin_required
	def download_content_master_report():
		headers = ["Content ID", "Title", "Content Type", "Category", "Created By", "Created Date", "Status", "Published Date", "Published By"]
		query = """
			SELECT p.id, p.title, p.content_type, p.category, 
				   u1.full_name, p.created_at, p.status, 
				   p.published_at, u2.full_name
			FROM posts p
			JOIN users u1 ON u1.id = p.created_by
			LEFT JOIN users u2 ON u2.id = p.published_by
			ORDER BY p.id ASC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Content_Master_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/content-engagement/download")
	@admin_required
	def download_content_engagement_report():
		headers = ["Content ID", "Content Name", "Views", "Average Rating", "Number of Ratings", "Number of Comments"]
		query = """
			SELECT p.id, p.title, p.views,
				   COALESCE((SELECT ROUND(AVG(r.rating), 1) FROM post_ratings r WHERE r.post_id = p.id), 0.0),
				   (SELECT COUNT(*) FROM post_ratings r WHERE r.post_id = p.id),
				   (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.id)
			FROM posts p
			ORDER BY p.id ASC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Content_Engagement_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/content-approval/download")
	@admin_required
	def download_content_approval_report():
		headers = ["Content ID", "Created By", "Submitted Date", "Approval Date", "Approved By", "Status", "Rejection Reason", "Version"]
		query = """
			SELECT h.post_id, u1.full_name,
				   h.submitted_at, h.reviewed_at,
				   u2.full_name, h.new_status,
				   h.comments, h.version_number
			FROM post_approval_history h
			JOIN posts p ON p.id = h.post_id
			JOIN users u1 ON u1.id = p.created_by
			LEFT JOIN users u2 ON u2.id = h.reviewed_by
			ORDER BY h.id ASC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Content_Approval_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/user-content/download")
	@admin_required
	def download_user_content_report():
		headers = ["User", "Total Posts", "Published Posts", "Pending Posts", "Rejected Posts", "Average Rating", "Total Comments"]
		query = """
			SELECT u.full_name,
				   (SELECT COUNT(*) FROM posts p WHERE p.created_by = u.id),
				   (SELECT COUNT(*) FROM posts p WHERE p.created_by = u.id AND p.status = 'PUBLISHED'),
				   (SELECT COUNT(*) FROM posts p WHERE p.created_by = u.id AND p.status = 'PENDING_APPROVAL'),
				   (SELECT COUNT(*) FROM posts p WHERE p.created_by = u.id AND p.status = 'REJECTED'),
				   COALESCE((SELECT ROUND(AVG(r.rating), 1) FROM post_ratings r JOIN posts p ON p.id = r.post_id WHERE p.created_by = u.id), 0.0),
				   (SELECT COUNT(*) FROM post_comments c JOIN posts p ON p.id = c.post_id WHERE p.created_by = u.id)
			FROM users u
			ORDER BY (SELECT COUNT(*) FROM posts p WHERE p.created_by = u.id) DESC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="User_Content_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/assessment-results/download")
	@admin_required
	def download_assessment_results_report():
		headers = ["Attempt ID", "Student Name", "Username", "Course Name", "Assessment Title", "Attempt Number", "Score", "Percentage", "Result", "Submitted At"]
		query = """
			SELECT aa.id, 
				   u.full_name, 
				   u.username, 
				   c.name, 
				   a.title, 
				   aa.attempt_no, 
				   aa.score, 
				   aa.percentage, 
				   aa.result, 
				   aa.submitted_at
			FROM assessment_attempts aa
			JOIN users u ON u.id = aa.student_id
			JOIN assessments a ON a.id = aa.assessment_id
			JOIN courses c ON c.id = a.course_id
			ORDER BY aa.id DESC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			row_list = list(r)
			if row_list[7] is not None:
				row_list[7] = round(row_list[7], 1)
			writer.writerow(row_list)
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Assessment_Results_Report.csv", mimetype="text/csv")

	@app.get("/rewards")
	def rewards_dashboard():
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		
		with get_db() as connection:
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
			if not wallet:
				wallet = {
					"current_balance": 0,
					"total_earned": 0,
					"total_settled": 0,
					"total_adjusted": 0
				}
				
			source_filter = request.args.get("source", "").strip()
			start_date = request.args.get("start_date", "").strip()
			end_date = request.args.get("end_date", "").strip()
			points_min = request.args.get("points_min", "").strip()
			points_max = request.args.get("points_max", "").strip()
			
			query = "SELECT * FROM reward_transactions WHERE user_id = ?"
			params = [user_id]
			
			if source_filter:
				query += " AND reward_source = ?"
				params.append(source_filter)
			if start_date:
				query += " AND DATE(created_at) >= DATE(?)"
				params.append(start_date)
			if end_date:
				query += " AND DATE(created_at) <= DATE(?)"
				params.append(end_date)
			if points_min:
				try:
					query += " AND ABS(points) >= ?"
					params.append(int(points_min))
				except ValueError:
					pass
			if points_max:
				try:
					query += " AND ABS(points) <= ?"
					params.append(int(points_max))
				except ValueError:
					pass
					
			query += " ORDER BY id DESC"
			transactions = connection.execute(query, params).fetchall()
			sources = connection.execute("SELECT name FROM reward_sources").fetchall()
			
		return render_template(
			"rewards.html", 
			wallet=wallet, 
			transactions=transactions, 
			sources=sources,
			user=session.get("user"),
			profile_picture=session.get("profile_picture"),
			role=session.get("role"),
			actual_role=session.get("actual_role")
		)

	@app.get("/admin/rewards")
	@admin_required
	def admin_rewards():
		with get_db() as connection:
			sources = connection.execute("SELECT * FROM reward_sources ORDER BY name ASC").fetchall()
			wallets = connection.execute(
				"""SELECT w.*, u.full_name, u.username 
				   FROM user_wallets w
				   JOIN users u ON u.id = w.user_id
				   ORDER BY w.current_balance DESC"""
			).fetchall()
			ledger = connection.execute(
				"""SELECT t.*, u.full_name, u.username
				   FROM reward_transactions t
				   JOIN users u ON u.id = t.user_id
				   ORDER BY t.id DESC LIMIT 100"""
			).fetchall()
			all_students = connection.execute("SELECT id, full_name, username FROM users WHERE role='basic' OR role='basic user'").fetchall()
			
		return render_template(
			"reward_admin.html",
			sources=sources,
			wallets=wallets,
			ledger=ledger,
			all_students=all_students,
			user=session.get("user"),
			profile_picture=session.get("profile_picture"),
			role=session.get("role"),
			actual_role=session.get("actual_role")
		)

	@app.post("/admin/rewards/source/update")
	@admin_required
	def admin_update_reward_source():
		name = request.form.get("name")
		status = request.form.get("status", "active")
		calc_type = request.form.get("calculation_type", "MULTIPLIER")
		multiplier = request.form.get("multiplier", 1.0)
		fixed_points = request.form.get("fixed_points", 0)
		
		try:
			multiplier = float(multiplier)
			fixed_points = int(fixed_points)
		except ValueError:
			flash("Invalid multiplier or fixed points value.")
			return redirect(url_for("admin_rewards"))
			
		with get_db() as connection:
			connection.execute(
				"""UPDATE reward_sources 
				   SET status = ?, calculation_type = ?, multiplier = ?, fixed_points = ? 
				   WHERE name = ?""",
				(status, calc_type, multiplier, fixed_points, name)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, 0)",
				(session.get("user_id"), f"Updated reward source rules: {name}", "reward_sources")
			)
			
		flash(f"Reward source '{name}' updated successfully.")
		return redirect(url_for("admin_rewards"))

	@app.post("/admin/rewards/settle")
	@admin_required
	def admin_settle_rewards():
		user_id = request.form.get("user_id")
		points = request.form.get("points", 0)
		remarks = request.form.get("remarks", "Settle points").strip()
		
		try:
			points = int(points)
		except ValueError:
			flash("Points must be an integer.")
			return redirect(url_for("admin_rewards"))
			
		if points <= 0:
			flash("Settlement points must be greater than zero.")
			return redirect(url_for("admin_rewards"))
			
		with get_db() as connection:
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
			if not wallet or wallet["current_balance"] < points:
				flash("Insufficient points balance for settlement.")
				return redirect(url_for("admin_rewards"))
				
			balance_before = wallet["current_balance"]
			balance_after = balance_before - points
			settlement_id = f"SETTLE-{user_id}-{os.urandom(3).hex().upper()}"
			
			connection.execute(
				"""INSERT INTO reward_transactions 
				   (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by, settlement_id)
				   VALUES (?, 'MANUAL_SETTLEMENT', ?, 'SETTLEMENT', ?, ?, 'SETTLEMENT', ?, ?, ?, ?)""",
				(user_id, settlement_id, remarks, -points, balance_before, balance_after, session.get("user_id"), settlement_id)
			)
			connection.execute(
				"""UPDATE user_wallets 
				   SET current_balance = ?, total_settled = ?
				   WHERE user_id = ?""",
				(balance_after, wallet["total_settled"] + points, user_id)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
				(session.get("user_id"), f"Settled {points} points. Settlement ID: {settlement_id}", "user_wallets", user_id)
			)
			
		flash(f"Successfully settled {points} points for user.")
		return redirect(url_for("admin_rewards"))

	@app.post("/admin/rewards/reset")
	@admin_required
	def admin_reset_rewards():
		user_id = request.form.get("user_id")
		confirm = request.form.get("confirm")
		
		if confirm != "YES":
			flash("Please confirm the warning checkboxes to execute a reset.")
			return redirect(url_for("admin_rewards"))
			
		with get_db() as connection:
			if user_id == "all":
				active_wallets = connection.execute("SELECT * FROM user_wallets WHERE current_balance > 0").fetchall()
				if not active_wallets:
					flash("No active wallets with positive balances to reset.")
					return redirect(url_for("admin_rewards"))
					
				for wallet in active_wallets:
					uid = wallet["user_id"]
					balance = wallet["current_balance"]
					
					connection.execute(
						"""INSERT INTO reward_transactions 
						   (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
						   VALUES (?, 'GLOBAL_RESET', 'RESET', 'ADJUSTMENT', 'Global reward points reset', ?, 'ADJUSTMENT', ?, 0, ?)""",
						(uid, -balance, balance, session.get("user_id"))
					)
					connection.execute(
						"""UPDATE user_wallets 
						   SET current_balance = 0, total_adjusted = ?
						   WHERE user_id = ?""",
						(wallet["total_adjusted"] + balance, uid)
					)
				
				connection.execute(
					"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, 0)",
					(session.get("user_id"), "Executed global rewards reset for all users", "user_wallets")
				)
				flash("Successfully executed a global reset of points for all users.")
				
			else:
				wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
				if not wallet or wallet["current_balance"] <= 0:
					flash("User has no points balance to reset.")
					return redirect(url_for("admin_rewards"))
					
				balance = wallet["current_balance"]
				
				connection.execute(
					"""INSERT INTO reward_transactions 
					   (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
					   VALUES (?, 'USER_RESET', 'RESET', 'ADJUSTMENT', 'User reward points reset', ?, 'ADJUSTMENT', ?, 0, ?)""",
					(user_id, -balance, balance, session.get("user_id"))
				)
				connection.execute(
					"""UPDATE user_wallets 
					   SET current_balance = 0, total_adjusted = ?
					   WHERE user_id = ?""",
					(wallet["total_adjusted"] + balance, user_id)
				)
				connection.execute(
					"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
					(session.get("user_id"), f"Reset user reward wallet to 0 (Deducted {balance} points)", "user_wallets", user_id)
				)
				flash(f"Successfully reset reward points to 0 for user.")
				
		return redirect(url_for("admin_rewards"))

	@app.post("/admin/rewards/adjust")
	@admin_required
	def admin_adjust_rewards():
		user_id = request.form.get("user_id")
		points = request.form.get("points", 0)
		remarks = request.form.get("remarks", "Manual adjustment").strip()
		
		try:
			points = int(points)
		except ValueError:
			flash("Adjustment points must be a non-zero integer.")
			return redirect(url_for("admin_rewards"))
			
		if points == 0:
			flash("Adjustment points cannot be zero.")
			return redirect(url_for("admin_rewards"))
			
		with get_db() as connection:
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
			if not wallet:
				connection.execute("INSERT INTO user_wallets (user_id, current_balance, total_earned, total_settled, total_adjusted) VALUES (?, 0, 0, 0, 0)", (user_id,))
				balance_before = 0
				total_earned = 0
				total_settled = 0
				total_adjusted = 0
			else:
				balance_before = wallet["current_balance"]
				total_earned = wallet["total_earned"]
				total_settled = wallet["total_settled"]
				total_adjusted = wallet["total_adjusted"]
				
			balance_after = balance_before + points
			if balance_after < 0:
				flash("Adjustment cannot result in a negative wallet balance.")
				return redirect(url_for("admin_rewards"))
				
			tx_ref = f"ADJUST-{os.urandom(3).hex().upper()}"
			tx_type = "ADJUSTMENT" if points > 0 else "REVERSAL"
			
			connection.execute(
				"""INSERT INTO reward_transactions 
				   (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
				   VALUES (?, 'MANUAL_ADJUSTMENT', ?, 'ADJUSTMENT', ?, ?, ?, ?, ?, ?)""",
				(user_id, tx_ref, remarks, points, tx_type, balance_before, balance_after, session.get("user_id"))
			)
			connection.execute(
				"""UPDATE user_wallets 
				   SET current_balance = ?, total_adjusted = ?
				   WHERE user_id = ?""",
				(balance_after, total_adjusted + abs(points), user_id)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
				(session.get("user_id"), f"Manual adjustment: {points:+} points ({remarks})", "user_wallets", user_id)
			)
			
		flash(f"Successfully adjusted user balance by {points:+} points.")
		return redirect(url_for("admin_rewards"))

	@app.get("/admin/reports/user-rewards/download")
	@admin_required
	def download_user_rewards_report():
		headers = ["User ID", "Full Name", "Username", "Current Balance", "Total Earned", "Total Settled", "Total Adjusted"]
		query = """
			SELECT u.id, u.full_name, u.username,
				   COALESCE(w.current_balance, 0),
				   COALESCE(w.total_earned, 0),
				   COALESCE(w.total_settled, 0),
				   COALESCE(w.total_adjusted, 0)
			FROM users u
			LEFT JOIN user_wallets w ON w.user_id = u.id
			ORDER BY COALESCE(w.current_balance, 0) DESC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="User_Rewards_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/reward-transactions/download")
	@admin_required
	def download_reward_transactions_report():
		headers = ["Transaction ID", "Student Name", "Username", "Reward Source", "Source Reference ID", "Source Reference Type", "Description", "Points", "Transaction Type", "Balance Before", "Balance After", "Date"]
		query = """
			SELECT t.id, u.full_name, u.username, t.reward_source, t.source_reference_id, t.source_reference_type,
				   t.description, t.points, t.transaction_type, t.balance_before, t.balance_after, t.created_at
			FROM reward_transactions t
			JOIN users u ON u.id = t.user_id
			ORDER BY t.id DESC
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Reward_Transactions_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/reward-sources/download")
	@admin_required
	def download_reward_sources_report():
		headers = ["Source Name", "Status", "Calculation Type", "Multiplier/Fixed Value", "Total Transactions", "Total Points Generated"]
		query = """
			SELECT s.name, s.status, s.calculation_type,
				   CASE WHEN s.calculation_type = 'MULTIPLIER' THEN s.multiplier ELSE s.fixed_points END,
				   COUNT(t.id),
				   COALESCE(SUM(t.points), 0)
			FROM reward_sources s
			LEFT JOIN reward_transactions t ON t.reward_source = s.name
			GROUP BY s.name
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			writer.writerow(list(r))
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Reward_Sources_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/course-owner-rewards/download")
	@admin_required
	def download_course_owner_rewards_report():
		headers = ["Course Name", "Course Owner Name", "Owner Username", "Number of Ratings", "Average Rating", "Reward Points Generated"]
		query = """
			SELECT c.name, u.full_name, u.username,
				   COUNT(cc.feedback_rating),
				   AVG(cc.feedback_rating),
				   (SELECT COALESCE(SUM(points), 0) FROM reward_transactions WHERE reward_source = 'COURSE_OWNER_RATING' AND user_id = c.created_by AND source_reference_id LIKE 'CRATE-' || c.id || '-%')
			FROM courses c
			JOIN users u ON u.id = c.created_by
			LEFT JOIN course_certifications cc ON cc.course_id = c.id
			GROUP BY c.id
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			row_list = list(r)
			if row_list[4] is not None:
				row_list[4] = round(row_list[4], 1)
			writer.writerow(row_list)
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Course_Owner_Rewards_Report.csv", mimetype="text/csv")

	@app.get("/admin/reports/community-content-rewards/download")
	@admin_required
	def download_community_content_rewards_report():
		headers = ["Post Title", "Post Owner Name", "Owner Username", "Number of Ratings", "Average Rating", "Reward Points Generated"]
		query = """
			SELECT p.title, u.full_name, u.username,
				   COUNT(r.rating),
				   AVG(r.rating),
				   (SELECT COALESCE(SUM(points), 0) FROM reward_transactions WHERE reward_source = 'COMMUNITY_POST_RATING' AND user_id = p.created_by AND source_reference_id LIKE 'PRATE-' || p.id || '-%')
			FROM posts p
			JOIN users u ON u.id = p.created_by
			LEFT JOIN post_ratings r ON r.post_id = p.id
			GROUP BY p.id
		"""
		with get_db() as connection:
			rows = connection.execute(query).fetchall()
		stream = StringIO()
		writer = csv.writer(stream)
		writer.writerow(headers)
		for r in rows:
			row_list = list(r)
			if row_list[4] is not None:
				row_list[4] = round(row_list[4], 1)
			writer.writerow(row_list)
		output = stream.getvalue().encode("utf-8-sig")
		return send_file(BytesIO(output), as_attachment=True, download_name="Community_Content_Rewards_Report.csv", mimetype="text/csv")

	@app.get("/logout")
	def logout():
		"""End the current session."""
		session.clear()
		return redirect(url_for("home"))

	# â”€â”€ API v1 Authentication & Routing Block â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

	@app.get("/api/v1/docs")
	def api_docs_playground():
		"""Display interactive API v1 documentation and sandbox playground."""
		return render_template(
			"api_docs.html",
			user=session.get("user"),
			role=session.get("role"),
			actual_role=session.get("actual_role"),
			profile_picture=session.get("profile_picture")
		)

	# â”€â”€ USERS API â”€â”€

	@app.get("/api/v1/users")
	@api_staff_required
	def api_list_users():
		"""List all system users."""
		with get_db() as connection:
			users = connection.execute("SELECT id, username, full_name, role FROM users ORDER BY id").fetchall()
		return {"users": [dict(u) for u in users]}

	@app.post("/api/v1/users")
	@api_admin_required
	def api_create_user():
		"""Create a new user profile."""
		data = request.get_json() or {}
		username = (data.get("username") or "").strip()
		full_name = (data.get("full_name") or "").strip()
		password = data.get("password")
		role = data.get("role", "basic user").strip()
		
		if not username or not full_name or not password:
			return {"error": "Missing required fields: username, full_name, password."}, 400
		if len(password) < 6:
			return {"error": "Password must be at least 6 characters."}, 400
		if role not in ROLES:
			return {"error": f"Invalid role. Must be one of: {list(ROLES)}."}, 400
			
		with get_db() as connection:
			existing = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
			if existing:
				return {"error": "Username already exists."}, 409
			try:
				user_id = connection.execute(
					"INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
					(username, generate_password_hash(password), role, full_name)
				).lastrowid
			except Exception as e:
				return {"error": f"Database insertion failed: {str(e)}"}, 500
		return {"message": "User created successfully.", "user_id": user_id}, 201

	@app.get("/api/v1/users/<int:user_id>")
	@api_required
	def api_get_user(user_id):
		"""Retrieve a user's details."""
		from flask import g
		if g.api_user["role"] not in ("admin", "moderator") and g.api_user["id"] != user_id:
			return {"error": "Access forbidden: you can only query your own profile."}, 403
		with get_db() as connection:
			u = connection.execute("SELECT id, username, full_name, role FROM users WHERE id = ?", (user_id,)).fetchone()
		if not u:
			return {"error": "User not found."}, 404
		return {"user": dict(u)}

	@app.get("/api/v1/users/<int:user_id>/download")
	@api_required
	def api_download_user_data(user_id):
		"""Retrieve and download a user's progress and wallet statistics."""
		from flask import g
		if g.api_user["role"] not in ("admin", "moderator") and g.api_user["id"] != user_id:
			return {"error": "Access forbidden: you can only download your own data."}, 403
			
		with get_db() as connection:
			user = connection.execute("SELECT id, username, full_name, role FROM users WHERE id = ?", (user_id,)).fetchone()
			if not user:
				return {"error": "User not found."}, 404
			
			assignments = connection.execute(
				"SELECT ca.*, c.name AS course_name, c.category FROM course_assignments ca JOIN courses c ON c.id = ca.course_id WHERE ca.student_id = ?",
				(user_id,)
			).fetchall()
			
			attempts = connection.execute(
				"SELECT a.*, ast.title AS assessment_title FROM assessment_attempts a JOIN assessments ast ON ast.id = a.assessment_id WHERE a.student_id = ?",
				(user_id,)
			).fetchall()
			
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
			
		return {
			"user": dict(user),
			"assignments": [dict(a) for a in assignments],
			"attempts": [dict(at) for at in attempts],
			"wallet": dict(wallet) if wallet else {"user_id": user_id, "current_balance": 0, "total_earned": 0, "total_settled": 0, "total_adjusted": 0}
		}


	@app.put("/api/v1/users/<int:user_id>")
	@api_admin_required
	def api_update_user(user_id):
		data = request.get_json() or {}
		full_name = data.get("full_name")
		if not full_name:
			return {"error": "Missing full_name."}, 400
		with get_db() as connection:
			connection.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
		return {"message": "User updated successfully."}

	@app.delete("/api/v1/users/<int:user_id>")
	@api_admin_required
	def api_delete_user(user_id):
		with get_db() as connection:
			connection.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
		return {"message": "User deactivated successfully."}
	# â”€â”€ COURSES API â”€â”€

	@app.get("/api/v1/courses")
	@api_required
	def api_list_courses():
		"""List all courses."""
		from flask import g
		with get_db() as connection:
			if g.api_user["role"] in ("admin", "moderator"):
				courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by ORDER BY c.id DESC").fetchall()
			else:
				courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by WHERE c.status = 'published' OR c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY c.id DESC", (g.api_user["id"], g.api_user["id"])).fetchall()
		return {"courses": [dict(c) for c in courses]}

	@app.post("/api/v1/courses")
	@api_staff_required
	def api_create_course():
		"""Create a new course."""
		from flask import g
		data = request.get_json() or {}
		name = (data.get("name") or "").strip()
		description = (data.get("description") or "").strip()
		category = (data.get("category") or "General").strip()
		content_type = (data.get("content_type") or "Text/Article").strip()
		content_url = (data.get("content_url") or "").strip()
		status = (data.get("status") or "draft").strip().upper()
		
		if not name:
			return {"error": "Missing required field: name."}, 400
		if content_type not in ("URL", "PDF", "Video", "PPT"):
			return {"error": "Invalid content type. Must be one of: URL, PDF, Video, PPT."}, 400
		if status not in ("DRAFT", "PUBLISHED"):
			return {"error": "Invalid status. Must be DRAFT or PUBLISHED."}, 400
			
		with get_db() as connection:
			try:
				course_id = connection.execute(
					"INSERT INTO courses (name, description, category, content_type, content_url, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
					(name, description, category, content_type, content_url, status, g.api_user["id"])
				).lastrowid
			except Exception as e:
				return {"error": f"Database insertion failed: {str(e)}"}, 500
		return {"message": "Course created successfully.", "course_id": course_id}, 201

	@app.get("/api/v1/courses/<int:course_id>")
	@api_required
	def api_get_course(course_id):
		"""Retrieve a course's contents and assessments."""
		from flask import g
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not course:
				return {"error": "Course not found."}, 404
			if not course_is_visible(connection, course_id, g.api_user["id"]):
				return {"error": "Access forbidden: you do not have access to this course."}, 403
			
			assessments = connection.execute("SELECT id, title, type, pass_percentage, max_attempts FROM assessments WHERE course_id = ?", (course_id,)).fetchall()
		return {
			"course": dict(course),
			"assessments": [dict(a) for a in assessments]
		}

	@app.post("/api/v1/courses/<int:course_id>/assign")
	@api_staff_required
	def api_assign_course(course_id):
		"""Assign a course to a basic student user."""
		from flask import g
		data = request.get_json() or {}
		student_id = data.get("student_id")
		if not student_id:
			return {"error": "Missing student_id in request body."}, 400
			
		with get_db() as connection:
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not course:
				return {"error": "Course not found."}, 404
			student = connection.execute("SELECT * FROM users WHERE id = ? AND role = 'basic user'", (student_id,)).fetchone()
			if not student:
				return {"error": "Student user not found."}, 404
			if student_id == course["created_by"]:
				return {"error": "Cannot assign a course to its owner."}, 400
				
			if user_has_course_access(connection, student_id, course_id):
				return {"message": "User already has access to this course."}, 200
				
			try:
				connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (course_id, student_id))
				connection.execute(
					"INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, group_id, group_name, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Individual', NULL, NULL, ?, ?, 'assigned', 'new')",
					(course_id, course["name"], student_id, student["full_name"], g.api_user["id"], g.api_user["full_name"])
				)
			except Exception as e:
				return {"error": f"Failed to assign course: {str(e)}"}, 500
		return {"message": "Course assigned successfully."}, 200

	# â”€â”€ COMMUNITY/SOCIAL API â”€â”€

	@app.get("/api/v1/posts")
	@api_required
	def api_list_posts():
		"""List all published community feed posts."""
		category = request.args.get("category")
		with get_db() as connection:
			if category:
				rows = connection.execute("SELECT p.*, u.full_name AS creator FROM posts p JOIN users u ON u.id = p.created_by WHERE p.status = 'PUBLISHED' AND p.category = ? ORDER BY p.id DESC", (category,)).fetchall()
			else:
				rows = connection.execute("SELECT p.*, u.full_name AS creator FROM posts p JOIN users u ON u.id = p.created_by WHERE p.status = 'PUBLISHED' ORDER BY p.id DESC").fetchall()
		return {"posts": [dict(r) for r in rows]}

	@app.post("/api/v1/posts")
	@api_required
	def api_create_post():
		"""Create a new community feed post."""
		from flask import g
		data = request.get_json() or {}
		title = (data.get("title") or "").strip()
		description = (data.get("description") or "").strip()
		content_type = (data.get("content_type") or "Text/Article").strip()
		category = (data.get("category") or "General").strip()
		topic_tag = (data.get("topic_tag") or "").strip()
		content_url = (data.get("content_url") or "").strip()
		
		if not title or not description:
			return {"error": "Missing title or description."}, 400
		if content_type not in ("Text/Article", "PDF", "Video", "Image", "PPT/PowerPoint"):
			return {"error": "Invalid content_type. Must be Text/Article, PDF, Video, Image, or PPT/PowerPoint."}, 400
			
		status = "PUBLISHED" if g.api_user["role"] in ("admin", "moderator") else "PENDING_APPROVAL"
		
		with get_db() as connection:
			try:
				cursor = connection.execute(
					"""INSERT INTO posts (title, description, content_type, category, topic_tag, created_by, status, version_number)
					   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
					(title, description, content_type, category, topic_tag, g.api_user["id"], status)
				)
				post_id = cursor.lastrowid
				cursor.close()
				
				if content_url:
					connection.execute(
						"""INSERT INTO post_attachments (post_id, file_name, file_type, file_path, file_size, uploaded_by)
						   VALUES (?, ?, 'url', ?, 0, ?)""",
						(post_id, "Attached Link", content_url, g.api_user["id"])
					)
				
				connection.execute(
					"""INSERT INTO post_approval_history (post_id, version_number, submitted_by, action, comments, previous_status, new_status)
					   VALUES (?, 1, ?, 'SUBMIT', 'Initial creation via API', 'NONE', ?)""",
					(post_id, g.api_user["id"], status)
				)
				
				if status == "PENDING_APPROVAL":
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"New content '{title}' is waiting for approval.", "pending_review")
				else:
					# Author Post reward trigger
					process_reward_event(
						connection=connection,
						user_id=g.api_user["id"],
						event_name="MY_POST_RATING",
						source_reference_id=f"POST-{post_id}",
						source_reference_type="POST_CREATION",
						description=f"Approved community post: {title}",
						input_value=0,
						actor_id=g.api_user["id"]
					)
			except Exception as e:
				import traceback
				traceback.print_exc()
				return {"error": f"Database insertion failed: {str(e)}"}, 500
		return {"message": "Post created successfully.", "post_id": post_id, "status": status}, 201

	@app.get("/api/v1/posts/<int:post_id>")
	@api_required
	def api_get_post(post_id):
		"""Retrieve a community post's details, comments, and ratings."""
		with get_db() as connection:
			post = connection.execute("SELECT p.*, u.full_name AS creator FROM posts p JOIN users u ON u.id = p.created_by WHERE p.id = ?", (post_id,)).fetchone()
			if not post:
				return {"error": "Post not found."}, 404
				
			comments = connection.execute("SELECT pc.*, u.full_name AS author FROM post_comments pc JOIN users u ON u.id = pc.user_id WHERE pc.post_id = ? ORDER BY pc.id ASC", (post_id,)).fetchall()
			rating_row = connection.execute("SELECT AVG(rating) as avg_rating, COUNT(rating) as rating_count FROM post_ratings WHERE post_id = ?", (post_id,)).fetchone()
			
		return {
			"post": dict(post),
			"comments": [dict(c) for c in comments],
			"ratings": {
				"average": round(rating_row["avg_rating"], 1) if rating_row and rating_row["avg_rating"] is not None else 0,
				"count": rating_row["rating_count"] if rating_row else 0
			}
		}

	@app.post("/api/v1/posts/<int:post_id>/rate")
	@api_required
	def api_rate_post(post_id):
		"""Submit a rating (1-5 stars) for a community post."""
		from flask import g
		data = request.get_json() or {}
		rating = data.get("rating")
		if rating is None or not (1 <= int(rating) <= 5):
			return {"error": "Rating must be an integer between 1 and 5."}, 400
		rating = int(rating)
		
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				return {"error": "Post not found."}, 404
			if post["created_by"] == g.api_user["id"]:
				return {"error": "You cannot rate your own post."}, 400
				
			existing = connection.execute("SELECT * FROM post_ratings WHERE post_id = ? AND user_id = ?", (post_id, g.api_user["id"])).fetchone()
			if existing:
				return {"error": "You have already rated this post."}, 409
				
			try:
				connection.execute(
					"""INSERT INTO post_ratings (post_id, user_id, rating, updated_at)
					   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
					   ON CONFLICT(post_id, user_id) DO UPDATE SET rating = excluded.rating, updated_at = CURRENT_TIMESTAMP""",
					(post_id, g.api_user["id"], rating)
				)
				
				ref_id = f"PRATE-{post_id}-{g.api_user['id']}"
				# 1. Post Owner Reward
				process_reward_event(
					connection=connection,
					user_id=post["created_by"],
					event_name="COMMUNITY_POST_RATING",
					source_reference_id=ref_id,
					source_reference_type="POST_RATING",
					description=f"Community Post Rating received (Post ID: {post_id}, Rating: {rating}/5)",
					input_value=rating,
					actor_id=g.api_user["id"]
				)
				# 2. Rating Giver Reward
				process_reward_event(
					connection=connection,
					user_id=g.api_user["id"],
					event_name="RATING_GIVEN",
					source_reference_id=ref_id,
					source_reference_type="POST_RATING",
					description=f"Rated community post (Post ID: {post_id})",
					actor_id=g.api_user["id"]
				)
			except Exception as e:
				return {"error": f"Rating transaction failed: {str(e)}"}, 500
		return {"message": "Rating submitted successfully."}, 200

	@app.post("/api/v1/posts/<int:post_id>/comment")
	@api_required
	def api_comment_post(post_id):
		"""Add a text comment to a community post."""
		from flask import g
		data = request.get_json() or {}
		comment_text = (data.get("comment") or "").strip()
		if not comment_text:
			return {"error": "Missing comment text in request body."}, 400
			
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				return {"error": "Post not found."}, 404
			try:
				comment_id = connection.execute(
					"INSERT INTO post_comments (post_id, user_id, comment) VALUES (?, ?, ?)",
					(post_id, g.api_user["id"], comment_text)
				).lastrowid
			except Exception as e:
				return {"error": f"Comment submission failed: {str(e)}"}, 500
		return {"message": "Comment submitted successfully.", "comment_id": comment_id}, 201

	# â”€â”€ ASSESSMENTS & GRADING API â”€â”€

	@app.get("/api/v1/assessments/<int:assessment_id>")
	@api_required
	def api_get_assessment(assessment_id):
		"""Retrieve assessment details and questions (excluding correct options for students)."""
		from flask import g
		with get_db() as connection:
			assessment = connection.execute(
				"SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id WHERE a.id = ?",
				(assessment_id,)
			).fetchone()
			if not assessment:
				return {"error": "Assessment not found."}, 404
				
			if not course_is_visible(connection, assessment["course_id"], g.api_user["id"]):
				return {"error": "Access forbidden: you do not have access to this course content."}, 403
				
			q_rows = connection.execute(
				"""SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option, q.marks, q.difficulty, q.topic_tag 
				   FROM questions q
				   JOIN assessment_questions aq ON aq.question_id = q.id
				   WHERE aq.assessment_id = ?
				   ORDER BY q.id""",
				(assessment_id,)
			).fetchall()
			
		questions = []
		is_staff = g.api_user["role"] in ("admin", "moderator")
		for q in q_rows:
			item = {
				"id": q["id"],
				"question_text": q["question_text"],
				"option_a": q["option_a"],
				"option_b": q["option_b"],
				"option_c": q["option_c"],
				"option_d": q["option_d"],
				"marks": q["marks"],
				"difficulty": q["difficulty"],
				"topic_tag": q["topic_tag"]
			}
			if is_staff:
				item["correct_option"] = q["correct_option"]
			questions.append(item)
			
		return {
			"assessment": dict(assessment),
			"questions": questions
		}

	@app.post("/api/v1/assessments/<int:assessment_id>/submit")
	@api_required
	def api_submit_assessment(assessment_id):
		"""Submit answers to an assessment for scoring, status tracking, and certification."""
		from flask import g
		data = request.get_json() or {}
		answers = data.get("answers")
		if not isinstance(answers, dict):
			return {"error": "Missing or invalid 'answers' dictionary in request body."}, 400
			
		with get_db() as connection:
			assessment = connection.execute(
				"SELECT a.*, c.name AS course_name, c.created_by AS course_owner_id FROM assessments a JOIN courses c ON c.id = a.course_id WHERE a.id = ?",
				(assessment_id,)
			).fetchone()
			if not assessment:
				return {"error": "Assessment not found."}, 404
				
			if not course_is_visible(connection, assessment["course_id"], g.api_user["id"]):
				return {"error": "Access forbidden: you do not have access to this course content."}, 403
				
			prior_attempts = connection.execute(
				"SELECT COUNT(*) as count FROM assessment_attempts WHERE assessment_id = ? AND student_id = ?",
				(assessment_id, g.api_user["id"])
			).fetchone()
			attempt_no = (prior_attempts["count"] or 0) + 1
			
			if attempt_no > assessment["max_attempts"]:
				return {"error": f"You have already reached the maximum limit of {assessment['max_attempts']} attempts."}, 403
				
			questions = connection.execute(
				"""SELECT q.* FROM questions q
				   JOIN assessment_questions aq ON aq.question_id = q.id
				   WHERE aq.assessment_id = ?""",
				(assessment_id,)
			).fetchall()
			
			if not questions:
				return {"error": "This assessment has no questions configured."}, 400
				
			total_marks = 0
			marks_obtained = 0
			correct_count = 0
			incorrect_count = 0
			
			answers_to_insert = []
			for q in questions:
				q_id_str = str(q["id"])
				user_ans = (answers.get(q_id_str) or "").strip().upper()
				total_marks += q["marks"]
				
				is_correct = 1 if user_ans == q["correct_option"].upper() else 0
				marks_awarded = q["marks"] if is_correct else 0
				
				if is_correct:
					correct_count += 1
				else:
					incorrect_count += 1
				marks_obtained += marks_awarded
				answers_to_insert.append((q["id"], user_ans, is_correct, marks_awarded))
				
			percentage = (marks_obtained / total_marks) * 100 if total_marks > 0 else 0
			result = "pass" if percentage >= assessment["pass_percentage"] else "fail"
			
			try:
				cursor = connection.execute(
					"""INSERT INTO assessment_attempts (assessment_id, student_id, attempt_no, score, percentage, status, result, submitted_at)
					   VALUES (?, ?, ?, ?, ?, 'submitted', ?, CURRENT_TIMESTAMP)""",
					(assessment_id, g.api_user["id"], attempt_no, marks_obtained, percentage, result)
				)
				attempt_id = cursor.lastrowid
				cursor.close()
				
				for q_id, selected, is_corr, awarded in answers_to_insert:
					connection.execute(
						"INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) VALUES (?, ?, ?, ?, ?)",
						(attempt_id, q_id, selected, is_corr, awarded)
					)
					
				if result == "pass" and assessment["type"] == "post":
					import string
					import random
					cert_uid = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
					
					cursor_cert = connection.execute(
						"INSERT INTO certificates (student_id, course_id, cert_uid) VALUES (?, ?, ?)",
						(g.api_user["id"], assessment["course_id"], cert_uid)
					)
					certificate_id = cursor_cert.lastrowid
					cursor_cert.close()
					
					connection.execute(
						"UPDATE course_assignments SET status='certified', completed_at=COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?",
						(assessment["course_id"], g.api_user["id"])
					)
					
					# 1. Course Certification Reward
					process_reward_event(
						connection=connection,
						user_id=g.api_user["id"],
						event_name="COURSE_CERTIFICATION",
						source_reference_id=certificate_id,
						source_reference_type="CERTIFICATE",
						description=f"Course Certification - {assessment['course_name']} (Score: {marks_obtained})",
						input_value=marks_obtained,
						actor_id=g.api_user["id"]
					)
					# 2. Owner Course Reward
					ref_id = f"CRATE-{assessment['course_id']}-{g.api_user['id']}"
					process_reward_event(
						connection=connection,
						user_id=assessment["course_owner_id"],
						event_name="COURSE_OWNER_RATING",
						source_reference_id=ref_id,
						source_reference_type="COURSE_RATING",
						description=f"Course Rating received - {assessment['course_name']} (Rating: 5/10)",
						input_value=5,
						actor_id=g.api_user["id"]
					)
			except Exception as e:
				return {"error": f"Submission transaction failed: {str(e)}"}, 500
				
		return {
			"message": "Assessment submitted and graded successfully.",
			"attempt_id": attempt_id,
			"score": marks_obtained,
			"total_questions": len(questions),
			"correct_answers": correct_count,
			"incorrect_answers": incorrect_count,
			"percentage": round(percentage, 1),
			"pass_percentage": assessment["pass_percentage"],
			"result": result.upper()
		}, 201

	@app.get("/api/v1/attempts/<int:attempt_id>")
	@api_required
	def api_get_attempt(attempt_id):
		"""Retrieve attempts score scorecard metrics."""
		from flask import g
		with get_db() as connection:
			attempt = connection.execute(
				"""SELECT a.*, ast.title AS assessment_title, ast.course_id, c.name AS course_name
				   FROM assessment_attempts a
				   JOIN assessments ast ON ast.id = a.assessment_id
				   JOIN courses c ON c.id = ast.course_id
				   WHERE a.id = ?""",
				(attempt_id,)
			).fetchone()
			if not attempt:
				return {"error": "Attempt not found."}, 404
			if g.api_user["role"] not in ("admin", "moderator") and g.api_user["id"] != attempt["student_id"]:
				return {"error": "Access forbidden: you do not have permission to view this scorecard."}, 403
				
			total_q = connection.execute("SELECT COUNT(*) as count FROM attempt_answers WHERE attempt_id = ?", (attempt_id,)).fetchone()
			correct_q = connection.execute("SELECT COUNT(*) as count FROM attempt_answers WHERE attempt_id = ? AND is_correct = 1", (attempt_id,)).fetchone()
			incorrect_q = connection.execute("SELECT COUNT(*) as count FROM attempt_answers WHERE attempt_id = ? AND is_correct = 0", (attempt_id,)).fetchone()
			
		return {
			"attempt": dict(attempt),
			"metrics": {
				"total_questions": total_q["count"] if total_q else 0,
				"correct_answers": correct_q["count"] if correct_q else 0,
				"incorrect_answers": incorrect_q["count"] if incorrect_q else 0
			}
		}

	@app.get("/api/v1/attempts/<int:attempt_id>/review")
	@api_required
	def api_get_attempt_review(attempt_id):
		"""Retrieve question-by-question response details (restricted to pass attempts)."""
		from flask import g
		with get_db() as connection:
			attempt = connection.execute("SELECT * FROM assessment_attempts WHERE id = ?", (attempt_id,)).fetchone()
			if not attempt:
				return {"error": "Attempt not found."}, 404
			if g.api_user["role"] not in ("admin", "moderator") and g.api_user["id"] != attempt["student_id"]:
				return {"error": "Access forbidden: unauthorized attempt access."}, 403
			if attempt["result"] != "pass":
				return {"error": "Access forbidden: answer reviews are restricted to passed attempts only."}, 403
				
			reviews = connection.execute(
				"""SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option, q.explanation,
						  aa.selected_option, aa.is_correct, aa.marks_awarded
				   FROM questions q
				   JOIN attempt_answers aa ON aa.question_id = q.id
				   WHERE aa.attempt_id = ?
				   ORDER BY q.id""",
				(attempt_id,)
			).fetchall()
			
		return {
			"attempt_id": attempt_id,
			"result": attempt["result"].upper(),
			"questions": [dict(r) for r in reviews]
		}

	# â”€â”€ REWARDS API â”€â”€


	@app.get("/api/v1/leaderboard")
	@api_required
	def api_get_leaderboard():
		with get_db() as connection:
			leaders = connection.execute('''
				SELECT u.id, u.username, u.full_name, w.total_earned 
				FROM wallets w JOIN users u ON u.id = w.user_id 
				ORDER BY w.total_earned DESC LIMIT 10
			''').fetchall()
		return {"leaderboard": [dict(l) for l in leaders]}

	@app.get("/api/v1/groups")
	@api_required
	def api_get_groups():
		with get_db() as connection:
			groups = connection.execute("SELECT id, name, description FROM groups ORDER BY id").fetchall()
		return {"groups": [dict(g) for g in groups]}
	@app.get("/api/v1/rewards/balance")
	@api_required
	def api_get_reward_balance():
		"""Retrieve reward wallet points balance cache."""
		from flask import g
		with get_db() as connection:
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (g.api_user["id"],)).fetchone()
		if not wallet:
			return {"user_id": g.api_user["id"], "current_balance": 0, "total_earned": 0, "total_settled": 0, "total_adjusted": 0}
		return {"wallet": dict(wallet)}

	@app.get("/api/v1/rewards/transactions")
	@api_required
	def api_get_reward_transactions():
		"""Retrieve reward transactions history ledger."""
		from flask import g
		with get_db() as connection:
			txs = connection.execute("SELECT * FROM reward_transactions WHERE user_id = ? ORDER BY id DESC", (g.api_user["id"],)).fetchall()
		return {"transactions": [dict(t) for t in txs]}

	@app.post("/api/v1/rewards/settle")
	@api_admin_required
	def api_settle_rewards():
		"""Perform admin settlement on user reward points balance."""
		data = request.get_json() or {}
		target_user_id = data.get("target_user_id")
		points = data.get("points")
		if not target_user_id or points is None or int(points) <= 0:
			return {"error": "Missing or invalid target_user_id or positive points parameter."}, 400
		points = int(points)
		
		with get_db() as connection:
			user = connection.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
			if not user:
				return {"error": "User not found."}, 404
				
			wallet = connection.execute("SELECT current_balance FROM user_wallets WHERE user_id = ?", (target_user_id,)).fetchone()
			balance = wallet["current_balance"] if wallet else 0
			if balance < points:
				return {"error": f"Insufficient reward balance. User only has {balance} points."}, 400
				
			try:
				import uuid
				ref_id = f"SETTLE-{uuid.uuid4().hex[:8]}"
				connection.execute(
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after)
					   VALUES (?, 'MANUAL_SETTLEMENT', ?, 'ADMIN_SETTLEMENT', 'Points settled by Administrator', ?, 'SETTLEMENT', ?, ?)""",
					(target_user_id, ref_id, points, balance, balance - points)
				)
				connection.execute(
					"UPDATE user_wallets SET current_balance = current_balance - ?, total_settled = total_settled + ? WHERE user_id = ?",
					(points, points, target_user_id)
				)
			except Exception as e:
				return {"error": f"Settlement transaction failed: {str(e)}"}, 500
		return {"message": "Rewards settled successfully."}, 200

	@app.post("/api/v1/rewards/adjust")
	@api_admin_required
	def api_adjust_rewards():
		"""Manually adjust user wallet points balance (CREDIT or DEBIT)."""
		data = request.get_json() or {}
		target_user_id = data.get("target_user_id")
		points = data.get("points")
		description = (data.get("description") or "Balance manual adjustment by Administrator").strip()
		
		if not target_user_id or points is None:
			return {"error": "Missing target_user_id or points parameters."}, 400
		points = int(points)
		
		with get_db() as connection:
			user = connection.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
			if not user:
				return {"error": "User not found."}, 404
				
			connection.execute("INSERT OR IGNORE INTO user_wallets (user_id, current_balance, total_earned, total_settled, total_adjusted) VALUES (?, 0, 0, 0, 0)", (target_user_id,))
			wallet = connection.execute("SELECT current_balance FROM user_wallets WHERE user_id = ?", (target_user_id,)).fetchone()
			balance = wallet["current_balance"] if wallet else 0
			
			if points < 0 and balance < abs(points):
				return {"error": f"Cannot deduct {abs(points)} points. Wallet balance is only {balance}."}, 400
				
			new_balance = balance + points
			
			try:
				import uuid
				ref_id = f"ADJ-{uuid.uuid4().hex[:8]}"
				connection.execute(
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after)
					   VALUES (?, 'MANUAL_ADJUSTMENT', ?, 'ADMIN_ADJUSTMENT', ?, ?, 'ADJUSTMENT', ?, ?)""",
					(target_user_id, ref_id, description, abs(points), balance, new_balance)
				)
				connection.execute(
					"UPDATE user_wallets SET current_balance = ?, total_adjusted = total_adjusted + ? WHERE user_id = ?",
					(new_balance, points, target_user_id)
				)
			except Exception as e:
				return {"error": f"Adjustment failed: {str(e)}"}, 500
		return {"message": "Rewards adjusted successfully.", "new_balance": new_balance}, 200

	@app.post("/api/v1/rewards/reset")
	@api_admin_required
	def api_reset_rewards():
		"""Reset user reward balance to zero."""
		data = request.get_json() or {}
		target_user_id = data.get("target_user_id")
		if not target_user_id:
			return {"error": "Missing target_user_id parameter in request body."}, 400
			
		with get_db() as connection:
			user = connection.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
			if not user:
				return {"error": "User not found."}, 404
				
			wallet = connection.execute("SELECT current_balance FROM user_wallets WHERE user_id = ?", (target_user_id,)).fetchone()
			balance = wallet["current_balance"] if wallet else 0
			if balance == 0:
				return {"message": "User balance is already 0."}, 200
				
			try:
				import uuid
				ref_id = f"RESET-{uuid.uuid4().hex[:8]}"
				connection.execute(
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after)
					   VALUES (?, 'USER_RESET', ?, 'ADMIN_RESET', 'Rewards wallet reset to zero by Administrator', ?, 'SETTLEMENT', ?, 0)""",
					(target_user_id, ref_id, balance, balance)
				)
				connection.execute(
					"UPDATE user_wallets SET current_balance = 0, total_adjusted = total_adjusted - ? WHERE user_id = ?",
					(balance, target_user_id)
				)
			except Exception as e:
				return {"error": f"Reset operation failed: {str(e)}"}, 500
		return {"message": "Rewards balance reset to zero successfully."}, 200

	return app


app = create_app()


if __name__ == "__main__":
	app.run(debug=True)


