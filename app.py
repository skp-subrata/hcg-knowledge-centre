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
from flask import Flask, flash, g, redirect, render_template, request, send_file, send_from_directory, session, url_for, jsonify
from openpyxl import Workbook, load_workbook
from storage import save_file
from db_init import apply_init_scripts, applied_scripts
from security import attachment_allowed, is_safe_proxy_target, load_or_create_secret_key, sanitize_html, serve_inline
from csrf import init_csrf


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
	# Every engine transaction is a source-driven earning or its correction, so the net
	# goes to total_earned. total_adjusted is reserved for manual administrator operations.
	total_earned += points_to_award

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
			CREATE TABLE IF NOT EXISTS group_moderators (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
				user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				status TEXT DEFAULT 'Active',
				assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
				UNIQUE(group_id, user_id)
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
						CREATE TABLE IF NOT EXISTS app_releases (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				version_number TEXT UNIQUE NOT NULL,
				release_title TEXT NOT NULL,
				release_date TEXT DEFAULT CURRENT_TIMESTAMP,
				features TEXT,
				improvements TEXT,
				bug_fixes TEXT,
				is_active INTEGER DEFAULT 0
			);

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
				status TEXT CHECK(status IN ('DRAFT', 'PENDING_APPROVAL', 'PUBLISHED', 'REJECTED', 'UNPUBLISHED', 'INACTIVE')) DEFAULT 'DRAFT',
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
		# Apply the SQL init scripts in init_scripts/ (master tables, interests,
		# profile columns, starter master data). Each script runs once per database.
		apply_init_scripts(connection)
		# Demo data (sample users, demo accounts, demo courses) is for local use.
		# Deployments set LMS_SEED_DEMO=0 to get only the schema, master data and the bootstrap admin.
		if os.getenv("LMS_SEED_DEMO", "1") == "1":
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

	# Demo accounts documented in README.md (password == username). Local use only.
	for full_name, username, role in (("Admin", "admin", "admin"), ("Moderator", "mod", "moderator"), ("Student", "student", "basic user")):
		connection.execute(
			"INSERT OR IGNORE INTO users (full_name, username, password_hash, role, employee_id, department, location, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(full_name, username, generate_password_hash(os.getenv("LMS_ADMIN_PASSWORD") or "admin" if username == "admin" else username), role, f"EMP-{username.upper()}", "Operations", "Hyderabad", 1),
		)

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
	# notifications has no unique key, so INSERT OR IGNORE would add a duplicate on every start-up.
	if not connection.execute("SELECT 1 FROM notifications WHERE user_id = ? AND message = 'Python Foundations is ready for you.'", (student,)).fetchone():
		connection.execute("INSERT INTO notifications (user_id, message, type) VALUES (?, 'Python Foundations is ready for you.', 'assignment')", (student,))
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
				"SELECT ac.*, u.username, u.role, u.full_name FROM api_credentials ac JOIN users u ON u.id = ac.user_id WHERE ac.api_key = ? AND ac.api_secret = ? AND ac.status = 'active' AND COALESCE(u.is_active, 1) = 1",
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


def staff_session_or_api_required(view):
	"""Allow a logged-in staff session (the Admin page) or valid API-key headers.

	Populates ``g.api_user`` either way so the view can rely on it.
	"""
	@wraps(view)
	def wrapped(*args, **kwargs):
		if session.get("user_id") and session.get("role") in ("admin", "moderator"):
			g.api_user = {
				"id": session["user_id"],
				"username": None,
				"role": session["role"],
				"full_name": session.get("user"),
			}
			return view(*args, **kwargs)
		return api_required(view)(*args, **kwargs)
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
	user = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
	role = user["role"] if user else "basic user"
	course = connection.execute("SELECT status, created_by FROM courses WHERE id = ?", (course_id,)).fetchone()
	if not course: return False
	
	status = (course["status"] or "published").lower()
	is_admin = (role == "admin")
	is_creator = (course["created_by"] == user_id)
	
	if status in ("draft", "inactive"):
		return is_admin or is_creator
		
	if role in ("admin", "moderator"):
		return True
		
	if course["created_by"] == user_id:
		return False
		
	assignment = connection.execute("SELECT 1 FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, user_id)).fetchone()
	return status in ('published', 'active') or assignment is not None



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


def int_or(value, default):
	"""Parse an integer from a form/DB value; blank or invalid values fall back to *default*."""
	try:
		return int(str(value).strip())
	except (TypeError, ValueError):
		return default


def issue_certificate(connection, user_id, course_id):
	"""Return the learner's certificate uid for a course, creating the row only once."""
	existing = connection.execute(
		"SELECT cert_uid FROM certificates WHERE student_id = ? AND course_id = ?", (user_id, course_id)
	).fetchone()
	if existing:
		return existing["cert_uid"]
	cert_uid = f"CERT-{course_id}-{user_id}-{os.urandom(4).hex().upper()}"
	connection.execute(
		"INSERT INTO certificates (student_id, course_id, cert_uid, issued_date, file_url) VALUES (?, ?, ?, DATE('now'), '')",
		(user_id, course_id, cert_uid),
	)
	return cert_uid


def course_requires_post_assessment(connection, course_id):
	"""True when the course has a 'post' assessment; only those certify (a 'pre' check is a readiness test)."""
	return connection.execute(
		"SELECT 1 FROM assessments WHERE course_id = ? AND type = 'post' LIMIT 1", (course_id,)
	).fetchone() is not None


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
			existing_question = connection.execute("SELECT id FROM questions WHERE question_bank_id = ? AND question_text = ?", (bank[0], str(data.get("question_text")).strip())).fetchone()
			if existing_question:
				question = existing_question["id"]
			else:
				question = connection.execute("INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (bank[0], data["question_text"], data["option_a"], data["option_b"], data["option_c"], data["option_d"], correct, int(data.get("marks") or 1), data.get("difficulty") or "medium", data.get("topic_tag") or "", user_id, explanation)).lastrowid
			title = data.get("assessment_title") or f"{course['name']} assessment"
			assessment = connection.execute("SELECT id FROM assessments WHERE course_id = ? AND title = ?", (course_id, title)).fetchone()
			if not assessment:
				assessment = (connection.execute("INSERT INTO assessments (course_id, type, title) VALUES (?, ?, ?)", (course_id, str(data.get("assessment_type") or "post").lower(), title)).lastrowid,)
			connection.execute("INSERT OR IGNORE INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (assessment[0], question))
			if not existing_question:
				created += 1
	return created, rejected


def safe_referrer(default_url):
	from flask import request
	ref = request.referrer
	if ref and ref.startswith(request.host_url):
		return ref
	return default_url

def create_app():
	"""Build and configure the Flask application."""
	app = Flask(__name__)
	# LMS_SECRET_KEY wins; otherwise a key is generated once and kept in .secret_key (git-ignored).
	app.secret_key = os.getenv("LMS_SECRET_KEY") or load_or_create_secret_key(os.getenv("LMS_SECRET_KEY_FILE", Path(__file__).with_name(".secret_key")))
	app.config["TEMPLATES_AUTO_RELOAD"] = True
	app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
	app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
	app.config["CSRF_ENABLED"] = os.getenv("LMS_CSRF", "1") == "1"
	init_csrf(app)
	if os.getenv("LMS_PROXY_FIX", "0") == "1":
		# Behind Render/Heroku-style proxies: trust X-Forwarded-For/Proto/Host so request.host_url, the CSRF referrer check and redirects see https.
		from werkzeug.middleware.proxy_fix import ProxyFix
		app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
	if os.getenv("LMS_SECURE_COOKIES", "0") == "1":
		app.config["SESSION_COOKIE_SECURE"] = True

	ERROR_PAGES = {
		403: ("Access denied", "You don't have permission to view this page."),
		404: ("Page not found", "The page you're looking for doesn't exist or has moved."),
		405: ("Action not allowed", "That request isn't allowed here. Use the buttons and links on the page."),
		413: ("File too large", "That upload is bigger than the 100 MB limit. Compress it or share a link instead."),
		500: ("Something went wrong", "An unexpected error occurred. Please try again; if it keeps happening, tell an administrator."),
	}

	@app.errorhandler(403)
	@app.errorhandler(404)
	@app.errorhandler(405)
	@app.errorhandler(413)
	@app.errorhandler(500)
	def render_error_page(error):
		"""Branded error pages for browsers, JSON for API and AJAX callers."""
		code = getattr(error, "code", 500) or 500
		title, message = ERROR_PAGES.get(code, ERROR_PAGES[500])
		if request.path.startswith("/api/") or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
			return jsonify({"error": title, "message": message, "status": code}), code
		return render_template("error.html", code=code, title=title, message=message), code
	app.jinja_env.globals["embed_url"] = embed_url

	app.jinja_env.filters["sanitize"] = sanitize_html

	@app.template_filter("fromjson")
	def fromjson_filter(value):
		"""Parse a JSON string (release notes store their lists as JSON); anything else becomes []."""
		import json
		if not isinstance(value, str):
			return value or []
		try:
			return json.loads(value)
		except ValueError:
			return []
	init_db()

	@app.route("/", methods=["GET", "POST"])
	def home():
		"""Authenticate users and show their permitted courses."""
		if request.method == "POST":
			username = request.form.get("username", "").strip().lower()
			password = request.form.get("password", "")
			with get_db() as connection:
				user = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
			if user and user["is_active"] in (None, 1) and check_password_hash(user["password_hash"], password):
				session.pop("impersonator_id", None)
				session.update(
                    user=user["full_name"], 
                    user_id=user["id"], 
                    actual_role=user["role"], 
                    role="basic user", # Always login as basic user
                    profile_picture=user["profile_picture"] if "profile_picture" in user.keys() else ""
                )
				return redirect(url_for("home"))
			flash("Invalid username or password.", "error")
		with get_db() as connection:
			user_id = session.get("user_id", 0)
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
				ORDER BY c.id DESC
			""", (user_id,)).fetchall()
			
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
				   WHERE LOWER(IFNULL(status, 'published')) NOT IN ('draft', 'inactive')
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
			
			avail_sql = """SELECT c.*, creator.full_name AS course_owner,
				   (SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS avg_rating,
				   (SELECT COUNT(*) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS rating_count
				   FROM courses c
				   LEFT JOIN users creator ON c.created_by = creator.id
				   WHERE LOWER(IFNULL(c.status, 'published')) IN ('published', 'active')
				     AND c.id NOT IN (SELECT course_id FROM course_assignments WHERE student_id = ?)
				   ORDER BY c.id DESC"""
			avail_params = [session.get("user_id", 0)]
			
			available_courses = connection.execute(avail_sql, avail_params).fetchall()

		with get_db() as connection:
			if session.get("role") in ("admin", "moderator"):
				assessments = connection.execute("SELECT DISTINCT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id LEFT JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE c.created_by = ? OR ca.student_id IS NOT NULL ORDER BY a.id DESC", (session.get("user_id", 0), session.get("user_id", 0))).fetchall()
			else:
				assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id JOIN course_assignments ca ON ca.course_id = c.id AND ca.student_id = ? WHERE ca.status IN ('in_progress', 'assessment_pending', 'assessment_failed', 'feedback_pending', 'completed') ORDER BY a.id DESC", (session.get("user_id", 0),)).fetchall()
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
			if session.get("role") not in ("admin", "moderator"):
				flash("Only administrators and moderators can create groups.")
				return redirect(safe_referrer(url_for("groups_page")))
			name = request.form.get("name", "").strip()
			description = request.form.get("description", "").strip()
			group_type = request.form.get("group_type", "").strip()
			status = request.form.get("status", "active").strip() or "active"
			if not name:
				flash("Group name is required.", "error")
				return redirect(safe_referrer(url_for("groups_page")))
			with get_db() as connection:
				cursor = connection.execute(
					"INSERT INTO groups (name, description, group_type, status, created_by) VALUES (?, ?, ?, ?, ?)",
					(name, description, group_type, status, session["user_id"])
				)
				group_id = cursor.lastrowid
				connection.execute("INSERT INTO group_moderators (group_id, user_id, status) VALUES (?, ?, 'Active')", (group_id, session["user_id"]))
				selected = request.form.getlist("selected_users")
				for raw_user_id in selected:
					user_id = int(raw_user_id)
					connection.execute(
						"INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) SELECT ?, u.id, COALESCE(u.employee_id, ''), COALESCE(u.email, ''), COALESCE(u.department, ''), COALESCE(u.location, ''), CASE WHEN COALESCE(u.is_active, 1) = 1 THEN 'active' ELSE 'inactive' END FROM users u WHERE u.id = ?",
						(group_id, user_id)
				)
			flash("Group created successfully.", "success")
			return redirect(safe_referrer(url_for("groups_page")))
		with get_db() as connection:
			if session.get("role") == "admin":
				groups = connection.execute("""
					SELECT g.*, u.full_name AS creator_name,
					(SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) AS member_count,
					(SELECT COUNT(DISTINCT gca.course_id) FROM group_course_assignments gca WHERE gca.group_id = g.id) AS course_count
					FROM groups g
					JOIN users u ON u.id = g.created_by
					ORDER BY g.id DESC
				""").fetchall()
			else:
				groups = connection.execute("""
					SELECT g.*, u.full_name AS creator_name,
					(SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) AS member_count,
					(SELECT COUNT(DISTINCT gca.course_id) FROM group_course_assignments gca WHERE gca.group_id = g.id) AS course_count
					FROM groups g
					JOIN group_moderators gmod ON g.id = gmod.group_id
					JOIN users u ON u.id = g.created_by
					WHERE gmod.user_id = ? AND gmod.status = 'Active'
					ORDER BY g.id DESC
				""", (session["user_id"],)).fetchall()
			users = connection.execute("""
				SELECT u.id, u.full_name, u.username, u.role, u.employee_id, 
				       u.department, u.department_id,
				       COALESCE(d.department_name, u.department, '') AS resolved_department,
				       u.location, COALESCE(u.is_active, 1) AS is_active 
				FROM users u
				LEFT JOIN departments d ON d.department_id = u.department_id
				ORDER BY u.full_name
			""").fetchall()
			master_depts = connection.execute("""
				SELECT department_id AS id, department_name 
				FROM departments 
				WHERE LOWER(COALESCE(status, 'active')) = 'active' 
				ORDER BY department_name
			""").fetchall()
		return render_template("groups.html", groups=groups, users=users, master_depts=master_depts, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.get("/groups/<int:group_id>")
	@staff_required
	def group_detail(group_id):
		"""Display group summary, members, and assigned courses."""
		with get_db() as connection:
			group = connection.execute("SELECT g.*, u.full_name AS creator_name FROM groups g JOIN users u ON u.id = g.created_by WHERE g.id = ?", (group_id,)).fetchone()
			if not group:
				flash("Group not found.", "error")
				return redirect(safe_referrer(url_for("groups_page")))
			if session.get("role") != "admin" and not connection.execute(
				"SELECT 1 FROM group_moderators WHERE group_id = ? AND user_id = ? AND status = 'Active'", (group_id, session.get("user_id"))
			).fetchone():
				flash("You can only view groups you moderate.", "error")
				return redirect(safe_referrer(url_for("groups_page")))
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
				(SELECT COUNT(*) FROM course_assignments ca JOIN group_members gm ON gm.user_id = ca.student_id WHERE ca.course_id = c.id AND gm.group_id = gca.group_id AND ca.status IN ('completed', 'certified')) AS completed_count,
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
			moderators = connection.execute("""
				SELECT gm.id, u.id AS user_id, u.full_name, u.role, gm.assigned_at, gm.status
				FROM group_moderators gm
				JOIN users u ON u.id = gm.user_id
				WHERE gm.group_id = ?
				ORDER BY u.full_name
			""", (group_id,)).fetchall()
			eligible_moderators = connection.execute("SELECT id, full_name FROM users WHERE role = 'moderator' AND id NOT IN (SELECT user_id FROM group_moderators WHERE group_id = ?) ORDER BY full_name", (group_id,)).fetchall()
		return render_template("group_detail.html", group=group, members=members, moderators=moderators, eligible_moderators=eligible_moderators, assigned_courses=assigned_courses, all_courses=all_courses, user_count=user_count, course_count=course_count, overall_progress=overall_progress, certified_count=certified_count, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.post("/groups/<int:group_id>/moderators")
	@admin_required
	def add_group_moderator(group_id):
		"""Add a moderator to the group."""
		user_id = request.form.get("moderator_id")
		if user_id:
			with get_db() as connection:
				try:
					connection.execute("INSERT INTO group_moderators (group_id, user_id) VALUES (?, ?)", (group_id, int(user_id)))
					flash("Moderator added to group.", "success")
				except Exception:
					flash("Could not add moderator.", "error")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/<int:group_id>/moderators/<int:user_id>/remove")
	@admin_required
	def remove_group_moderator(group_id, user_id):
		"""Remove a moderator from the group."""
		with get_db() as connection:
			connection.execute("DELETE FROM group_moderators WHERE group_id = ? AND user_id = ?", (group_id, user_id))
			flash("Moderator removed.", "success")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/<int:group_id>/moderators/<int:user_id>/toggle")
	@admin_required
	def toggle_group_moderator(group_id, user_id):
		"""Activate or deactivate a moderator."""
		with get_db() as connection:
			mod = connection.execute("SELECT status FROM group_moderators WHERE group_id = ? AND user_id = ?", (group_id, user_id)).fetchone()
			if mod:
				new_status = 'Inactive' if mod['status'].lower() == 'active' else 'Active'
				connection.execute("UPDATE group_moderators SET status = ? WHERE group_id = ? AND user_id = ?", (new_status, group_id, user_id))
				flash(f"Moderator status updated to {new_status}.", "success")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/<int:group_id>/members")
	@staff_required
	def add_group_members(group_id):
		"""Add selected users to an existing group."""
		if session.get("role") not in ("admin", "moderator"):
			return redirect(url_for("home"))
		with get_db() as connection:
			group = connection.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
			if not group:
				flash("Group not found.", "error")
				return redirect(safe_referrer(url_for("groups_page")))
			for raw_user_id in request.form.getlist("selected_users"):
				user_id = int(raw_user_id)
				connection.execute(
					"INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) SELECT ?, u.id, COALESCE(u.employee_id, ''), COALESCE(u.email, ''), COALESCE(u.department, ''), COALESCE(u.location, ''), CASE WHEN COALESCE(u.is_active, 1) = 1 THEN 'active' ELSE 'inactive' END FROM users u WHERE u.id = ?",
					(group_id, user_id)
				)
		flash("Selected users added to the group.", "success")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/<int:group_id>/remove-member")
	@staff_required
	def remove_group_member(group_id):
		"""Remove a user from a group while leaving any existing course access intact."""
		user_id = request.form.get("user_id")
		if user_id:
			with get_db() as connection:
				connection.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, int(user_id)))
		flash("User removed from group. Existing course access remains unchanged.", "success")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/<int:group_id>/assign-course")
	@staff_required
	def assign_group_course(group_id):
		"""Assign a course to all members of a group with duplicate checks only on user/course access."""
		course_id = request.form.get("course_id")
		if not course_id:
			flash("Please choose a course to assign.", "error")
			return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))
		with get_db() as connection:
			group = connection.execute("SELECT g.*, u.full_name AS creator_name FROM groups g JOIN users u ON u.id = g.created_by WHERE g.id = ?", (group_id,)).fetchone()
			course = connection.execute("SELECT * FROM courses WHERE id = ?", (int(course_id),)).fetchone()
			if not group or not course:
				flash("Group or course not found.", "error")
				return redirect(safe_referrer(url_for("groups_page")))
			existing = connection.execute("SELECT * FROM group_course_assignments WHERE group_id = ? AND course_id = ?", (group_id, int(course_id))).fetchone()
			if existing:
				flash("This course is already assigned to the group.", "error")
				return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))
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
		flash("Course assigned to the group. Existing access was preserved for users who already had the course.", "error")
		return redirect(safe_referrer(url_for("group_detail", group_id=group_id)))

	@app.post("/groups/upload-members")
	@staff_required
	def upload_group_members():
		"""Bulk upload members for a group using a simple CSV template."""
		group_id = request.form.get("group_id")
		file = request.files.get("members_file")
		if not group_id or not file or not file.filename:
			flash("Please select a group and a valid CSV upload.", "error")
			return redirect(safe_referrer(url_for("groups_page")))
		if not file.filename.lower().endswith(".csv"):
			flash("Please upload a CSV file.", "error")
			return redirect(safe_referrer(url_for("groups_page")))
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
				user = connection.execute("SELECT * FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
				if not user:
					user = connection.execute("SELECT * FROM users WHERE username = ? AND COALESCE(employee_id, '') = ''", (username.lower(),)).fetchone()
				if not user:
					invalid += 1
					continue
				if user["is_active"] is not None and user["is_active"] == 0:
					invalid += 1
					continue
				connection.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, employee_id, email, department, location, user_status) VALUES (?, ?, ?, ?, ?, ?, 'active')", (int(group_id), user["id"], user["employee_id"], user["email"], user["department"], user["location"]))
				added += 1
		flash(f"Bulk upload completed: {added} added, {duplicates} duplicates, {invalid} invalid rows.", "error")
		return redirect(safe_referrer(url_for("group_detail", group_id=int(group_id))))

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
			active_courses = connection.execute("SELECT COUNT(*) FROM courses WHERE LOWER(status) = 'published'").fetchone()[0]
			
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
				WHERE certification_status = 'CERTIFIED'
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
				email = request.form.get("email", "").strip()
				phone_number = request.form.get("phone_number", "").strip()
				department_id = request.form.get("department_id")
				department_id = int(department_id) if department_id else None
				position_id = request.form.get("position_id")
				position_id = int(position_id) if position_id else None
				location_id = request.form.get("location_id")
				location_id = int(location_id) if location_id else None
				about_me = request.form.get("about_me", "").strip()
				interests = request.form.getlist("interests")
				
				if not full_name or not username or len(password) < 6 or role not in ROLES or not employee_id or not email or not phone_number or not location_id:
					flash("Enter all mandatory fields (employee ID, email, phone, location) and use a password of at least 6 chars.", "error")
				else:
					try:
						with get_db() as connection:
							dup = connection.execute("SELECT employee_id, email, username FROM users WHERE username = ? OR employee_id = ? OR email = ?", (username, employee_id, email)).fetchone()
							if dup:
								if dup["employee_id"] == employee_id: flash("Employee ID already exists.", "error")
								elif dup["email"] == email: flash("Email already exists.", "error")
								else: flash("Username already exists.", "error")
							else:
								cursor = connection.execute(
									"INSERT INTO users (full_name, username, password_hash, role, employee_id, email, phone_number, department_id, position_id, location_id, about_me, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
									(full_name, username, generate_password_hash(password), role, employee_id, email, phone_number, department_id, position_id, location_id, about_me),
								)
								new_user_id = cursor.lastrowid
								for interest_id in interests:
									if str(interest_id).isdigit():
										connection.execute("INSERT OR IGNORE INTO user_interest (user_id, interest_id) VALUES (?, ?)", (new_user_id, int(interest_id)))

								flash("User added successfully.", "success")
					except sqlite3.IntegrityError:
						flash("Database integrity error occurred.", "error")
			elif action == "update_user" and session.get("role") == "admin":
				user_id = request.form.get("record_id")
				is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
				if str(user_id) == str(session["user_id"]):
					msg = "You cannot edit your own profile here. Use the Profile page."
					if is_ajax:
						return jsonify({"error": msg}), 400
					flash(msg)
				else:
					full_name = request.form.get("full_name", "").strip()
					username = request.form.get("username", "").strip().lower()
					role = request.form.get("role", "basic user")
					employee_id = request.form.get("employee_id", "").strip()
					email = request.form.get("email", "").strip()
					phone_number = request.form.get("phone_number", "").strip()
					department_id = request.form.get("department_id")
					department_id = int(department_id) if department_id else None
					position_id = request.form.get("position_id")
					position_id = int(position_id) if position_id else None
					location_id = request.form.get("location_id")
					location_id = int(location_id) if location_id else None
					about_me = request.form.get("about_me", "").strip()
					interests = request.form.getlist("interests")

					if not full_name or not username or not employee_id or not email or not phone_number:
						msg = "Full Name, Username, Employee ID, Email, and Phone Number are mandatory."
						if is_ajax:
							return jsonify({"error": msg}), 400
						flash(msg)
					else:
						with get_db() as connection:
							# Only check uniqueness for non-blank values to avoid false positives
							# when multiple users have empty employee_id or email
							dup_username = connection.execute(
								"SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id)
							).fetchone()
							dup_emp = connection.execute(
								"SELECT id FROM users WHERE employee_id = ? AND employee_id != '' AND id != ?", (employee_id, user_id)
							).fetchone() if employee_id else None
							dup_email = connection.execute(
								"SELECT id FROM users WHERE email = ? AND email != '' AND id != ?", (email, user_id)
							).fetchone() if email else None

							if dup_username:
								msg = "Username already in use."
								if is_ajax: return jsonify({"error": msg}), 409
								flash(msg)
							elif dup_emp:
								msg = "Employee ID already in use."
								if is_ajax: return jsonify({"error": msg}), 409
								flash(msg)
							elif dup_email:
								msg = "Email already in use."
								if is_ajax: return jsonify({"error": msg}), 409
								flash(msg)
							else:
								connection.execute(
									"UPDATE users SET full_name = ?, username = ?, role = ?, employee_id = ?, email = ?, phone_number = ?, department_id = ?, position_id = ?, location_id = ?, about_me = ? WHERE id = ?",
									(full_name, username, role, employee_id, email, phone_number, department_id, position_id, location_id, about_me, user_id),
								)
								if interests:  # replace the interest set only when the form sent one
									connection.execute("DELETE FROM user_interest WHERE user_id = ?", (user_id,))
									for interest_id in interests:
										if str(interest_id).isdigit():
											connection.execute("INSERT OR IGNORE INTO user_interest (user_id, interest_id) VALUES (?, ?)", (user_id, int(interest_id)))
								if is_ajax:
									return jsonify({"success": True, "message": "User updated successfully."})
								flash("User updated successfully.", "success")
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
					flash("Course created successfully.", "success")
			elif action == "update_course":
				with get_db() as connection:
					if course_is_manageable(connection, request.form["record_id"], session["user_id"], session["role"]):
						connection.execute(
							"UPDATE courses SET name = ?, description = ?, category = ?, status = ? WHERE id = ?",
							(request.form["name"].strip(), request.form.get("description", "").strip(), request.form.get("category", "General").strip(), request.form.get("status", "published"), request.form["record_id"]),
						)
						flash("Course updated successfully.", "success")
			elif action == "add_bank":
				with get_db() as connection:
					connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, ?, ?)", (request.form["bank_name"].strip(), request.form.get("category", "General").strip(), session["user_id"]))
				flash("Question bank created successfully.", "success")
			elif action == "add_question":
				with get_db() as connection:
					assessment = connection.execute("SELECT course_id, title FROM assessments WHERE id = ?", (request.form["assessment_id"],)).fetchone()
					if assessment and course_is_manageable(connection, assessment["course_id"], session["user_id"], session["role"]):
						bank_name = f"{assessment['title']} Question Bank"
						bank = connection.execute("SELECT id FROM question_banks WHERE name = ?", (bank_name,)).fetchone()
						if not bank:
							bank = (connection.execute("INSERT INTO question_banks (name, category, created_by) VALUES (?, 'Manual', ?)", (bank_name, session["user_id"])).lastrowid,)
						explanation = request.form.get("explanation", "").strip() or None
						correct_option = request.form.get("correct_option", "").strip().lower()
						if correct_option not in ("a", "b", "c", "d"):
							flash("The correct option must be A, B, C or D.", "error")
							return redirect(safe_referrer(url_for("admin_panel")))
						question_id = connection.execute(
							"INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, created_by, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
							(bank[0], request.form["question_text"].strip(), request.form["option_a"].strip(), request.form["option_b"].strip(), request.form["option_c"].strip(), request.form["option_d"].strip(), correct_option, int_or(request.form.get("marks"), 1), request.form.get("difficulty", "medium"), session["user_id"], explanation),
						).lastrowid
						connection.execute("INSERT INTO assessment_questions (assessment_id, question_id) VALUES (?, ?)", (request.form["assessment_id"], question_id))
						flash("Question added and linked to assessment successfully.", "success")
					else:
						flash("You can only manage courses you created.", "error")
			elif action == "add_assessment":
				with get_db() as connection:
					if course_is_manageable(connection, request.form["course_id"], session["user_id"], session["role"]):
						connection.execute("INSERT INTO assessments (course_id, type, title, pass_percentage, max_attempts) VALUES (?, ?, ?, ?, ?)", (request.form["course_id"], request.form["assessment_type"], request.form["assessment_title"].strip(), int_or(request.form.get("pass_percentage"), 60), int_or(request.form.get("max_attempts"), 1)))
						flash("Assessment created successfully.", "success")
					else:
						flash("You can only manage courses you created.", "error")
			elif action == "import_questions":
				file_obj = request.files.get("question_file")
				if not file_obj or not file_obj.filename.lower().endswith((".xlsx", ".csv")):
					flash("Upload an .xlsx or .csv question file.")
				else:
					try:
						created, rejected = import_questions(file_obj, session["user_id"], session["role"])
						flash(f"Imported {created} questions; rejected {rejected} rows.", "success")
					except (ValueError, KeyError, TypeError):
						flash("The workbook format is invalid. Download and use the template.", "error")
			elif action == "update_assessment":
				with get_db() as connection:
					course = connection.execute("SELECT course_id FROM assessments WHERE id = ?", (request.form["record_id"],)).fetchone()
					if course and course_is_manageable(connection, course["course_id"], session["user_id"], session["role"]):
						connection.execute("UPDATE assessments SET title = ?, type = ?, pass_percentage = ?, max_attempts = ? WHERE id = ?", (request.form["title"].strip(), request.form["type"], int_or(request.form.get("pass_percentage"), 60), int_or(request.form.get("max_attempts"), 1), request.form["record_id"]))
						flash("Assessment updated successfully.", "success")
			elif action == "generate_api_creds" and session.get("role") == "admin":
				target_user_id = request.form.get("target_user_id", type=int)
				if target_user_id is None:
					flash("Select a user.", "error")
					return redirect(safe_referrer(url_for("admin_panel")))
				import os
				api_key = "ak_" + os.urandom(16).hex()
				api_secret = "as_" + os.urandom(24).hex()
				with get_db() as connection:
					connection.execute("UPDATE api_credentials SET status = 'inactive' WHERE user_id = ?", (target_user_id,))
					connection.execute(
						"INSERT INTO api_credentials (user_id, api_key, api_secret, status) VALUES (?, ?, ?, 'active')",
						(target_user_id, api_key, api_secret)
					)
				flash("API credentials generated successfully.", "success")
			elif action == "revoke_api_creds" and session.get("role") == "admin":
				target_user_id = request.form.get("target_user_id", type=int)
				if target_user_id is None:
					flash("Select a user.", "error")
					return redirect(safe_referrer(url_for("admin_panel")))
				with get_db() as connection:
					connection.execute("UPDATE api_credentials SET status = 'inactive' WHERE user_id = ?", (target_user_id,))
				flash("API credentials revoked successfully.", "success")
			elif action == "assign_course":
				try:
					with get_db() as connection:
						assignment_type = request.form.get("assignment_type", "individual")
						course_id = int(request.form["course_id"])
						course_row = connection.execute("SELECT name, created_by FROM courses WHERE id = ?", (course_id,)).fetchone()
						if course_row is None:
							flash("Select a valid course.", "error")
							return redirect(safe_referrer(url_for("admin_panel")))
						course_name = course_row["name"]
						if assignment_type == "group":
							group_id = int(request.form["group_id"])
							group = connection.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
							if not group:
								flash("Select a valid group.", "error")
								return redirect(safe_referrer(url_for("admin_panel")))
							if session.get("role") != "admin":
								is_mod = connection.execute("SELECT 1 FROM group_moderators WHERE group_id = ? AND user_id = ? AND status = 'Active'", (group_id, session["user_id"])).fetchone()
								if not is_mod:
									flash("You can only assign courses to groups you moderate.", "error")
									return redirect(safe_referrer(url_for("admin_panel")))
							members = connection.execute("SELECT user_id FROM group_members WHERE group_id = ? ORDER BY user_id", (group_id,)).fetchall()
							for member in members:
								user_id = member["user_id"]
								if user_id == course_row["created_by"]:
									continue
								user = connection.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
								if user and not user_has_course_access(connection, user_id, course_id):
									connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (course_id, user_id))
									if user_id != session.get("user_id"):
										try:
											_c_name = connection.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()["name"]
											create_notification(connection, user_id, f"You have been assigned a new course: {_c_name}", "course_assigned", url_for("course_detail", course_id=course_id))
										except Exception:
											pass
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
								flash("Cannot assign a course to its owner.", "error")
								return redirect(safe_referrer(url_for("admin_panel")))
							user = connection.execute("SELECT full_name FROM users WHERE id = ?", (user_id,)).fetchone()
							if user and not user_has_course_access(connection, user_id, course_id):
								connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status = course_assignments.status", (course_id, user_id))
								if user_id != session.get("user_id"):
									try:
										_c_name = connection.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()["name"]
										create_notification(connection, user_id, f"You have been assigned a new course: {_c_name}", "course_assigned", url_for("course_detail", course_id=course_id))
									except Exception:
											pass
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
					flash("Course assignment processed. Existing course access was preserved when present.", "success")
				except (sqlite3.IntegrityError, KeyError, ValueError):
					flash("That course assignment could not be completed.", "error")

		with get_db() as connection:
			users = connection.execute("SELECT u.id, u.full_name, u.username, u.role, u.employee_id, u.email, u.phone_number, u.department_id, u.position_id, u.location_id, u.about_me, COALESCE(GROUP_CONCAT(DISTINCT ca.course_id), '') AS course_ids, COALESCE(GROUP_CONCAT(DISTINCT ui.interest_id), '') AS interest_ids FROM users u LEFT JOIN course_assignments ca ON ca.student_id = u.id LEFT JOIN user_interest ui ON ui.user_id = u.id GROUP BY u.id ORDER BY u.id").fetchall()
			master_depts = connection.execute("SELECT department_id as id, department_name as name FROM departments WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY department_name").fetchall()
			master_positions = connection.execute("SELECT id, name FROM positions WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name").fetchall()
			master_interests = connection.execute("SELECT id, interest_name as name FROM interest_master WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name").fetchall()
			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY location_name").fetchall()
			courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY c.id DESC", (session["user_id"], session["user_id"])).fetchall()
			students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user' ORDER BY full_name").fetchall()
			banks = connection.execute("SELECT * FROM question_banks ORDER BY id DESC").fetchall()
			assessments = connection.execute("SELECT a.*, c.name AS course_name FROM assessments a JOIN courses c ON c.id = a.course_id WHERE c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY a.id DESC", (session["user_id"], session["user_id"])).fetchall()
			if session.get("role") == "admin":
				groups = connection.execute("SELECT * FROM groups ORDER BY id DESC").fetchall()
			else:
				groups = connection.execute("SELECT g.* FROM groups g JOIN group_moderators gm ON g.id = gm.group_id WHERE gm.user_id = ? AND gm.status = 'Active' ORDER BY g.id DESC", (session["user_id"],)).fetchall()
			api_creds = connection.execute("SELECT ac.*, u.username, u.full_name, u.role FROM api_credentials ac JOIN users u ON u.id = ac.user_id ORDER BY ac.id DESC").fetchall() if session.get("role") == "admin" else []
			
			assignable_courses = connection.execute("SELECT id, name FROM courses WHERE LOWER(status) = 'published' ORDER BY name").fetchall()
		return render_template("admin.html", users=[dict(u) for u in users], courses=courses, assignable_courses=assignable_courses, students=students, banks=banks, assessments=assessments, groups=groups, api_creds=api_creds, content_types=CONTENT_TYPES, roles=ROLES, master_depts=master_depts, master_positions=master_positions, master_interests=master_interests, master_locations=master_locations, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.route("/assessments/<int:assessment_id>", methods=["GET", "POST"])
	def assessment(assessment_id):
		"""Display and grade a student's assessment while keeping failed attempts retryable."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		if session.get("role") == "admin":
			flash("Admins cannot take assessments.", "error")
			return redirect(safe_referrer(url_for("home")))
		with get_db() as connection:
			course_id_row = connection.execute("SELECT course_id FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
			if course_id_row:
				c_row = connection.execute("SELECT created_by FROM courses WHERE id = ?", (course_id_row["course_id"],)).fetchone()
				if c_row and c_row["created_by"] == session["user_id"]:
					flash("You cannot take an assessment for a course you created.", "error")
					return redirect(safe_referrer(url_for("course_detail", course_id=course_id_row["course_id"])))

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
				flash("Complete the course before starting the assessment.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
			if certification and certification["certification_status"] == "CERTIFIED":
				flash("This course is already certified. You can review the material and view your certificate, but you cannot retake the assessment.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
			if certification and certification["latest_assessment_status"] == "FEEDBACK_PENDING":
				return redirect(safe_referrer(url_for("feedback_form", course_id=assessment_row["course_id"])))
			assignment = connection.execute(
				"SELECT status FROM course_assignments WHERE course_id = ? AND student_id = ?",
				(assessment_row["course_id"], session["user_id"]),
			).fetchone()
			is_completed = assignment and get_course_status_label(assignment["status"]) in ("ASSESSMENT_PENDING", "IN_PROGRESS", "ASSESSMENT_FAILED")
		if not is_completed:
			flash("Complete the course before starting the assessment.", "error")
			return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
		if request.method == "POST":
			with get_db() as connection:
				cert_row = get_user_course_record(connection, session["user_id"], assessment_row["course_id"])
				if cert_row and cert_row["certification_status"] == "CERTIFIED":
					flash("This course is already certified.", "error")
					return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
				if not questions:
					flash("This assessment has no questions yet.", "error")
					return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
				attempt_count = connection.execute("SELECT COUNT(*) AS n FROM assessment_attempts WHERE assessment_id = ? AND student_id = ?", (assessment_id, session["user_id"])).fetchone()["n"]
				max_attempts = int_or(assessment_row["max_attempts"], 1)
				if attempt_count >= max_attempts:
					flash(f"You have used all {max_attempts} attempt(s) for this assessment.", "error")
					return redirect(safe_referrer(url_for("course_detail", course_id=assessment_row["course_id"])))
				pass_mark = int_or(assessment_row["pass_percentage"], 60)
				score = 0
				answers = []
				for question in questions:
					selected = request.form.get(f"q{question['id']}")
					correct = (selected or "").strip().lower() == (question["correct_option"] or "").strip().lower()
					marks = question["marks"] if correct else 0
					score += marks
					answers.append((question["id"], selected, correct, marks))
				percentage = (score / max(sum(q["marks"] for q in questions), 1)) * 100
				result = "pass" if percentage >= pass_mark else "fail"
				# Only a 'post' assessment leads to certification (unless the course has none); a 'pre' pass keeps the course in progress.
				certifiable = result == "pass" and (assessment_row["type"] == "post" or not course_requires_post_assessment(connection, assessment_row["course_id"]))
				next_status = "FEEDBACK_PENDING" if certifiable else ("IN_PROGRESS" if result == "pass" else "ASSESSMENT_FAILED")
				attempt_id = connection.execute(
					"INSERT INTO assessment_attempts (assessment_id, student_id, attempt_no, score, percentage, status, result, submitted_at) VALUES (?, ?, ?, ?, ?, 'submitted', ?, CURRENT_TIMESTAMP)",
					(assessment_id, session["user_id"], attempt_count + 1, score, percentage, result),
				).lastrowid
				for question_id, selected, correct, marks in answers:
					connection.execute("INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded) VALUES (?, ?, ?, ?, ?)", (attempt_id, question_id, selected, correct, marks))
				course = connection.execute("SELECT c.name FROM courses c WHERE c.id = ?", (assessment_row["course_id"],)).fetchone()
				cert_row = get_user_course_record(connection, session["user_id"], assessment_row["course_id"])
				if cert_row is None:
					connection.execute(
						"INSERT INTO course_certifications (user_id, course_id, user_name, course_name, course_start_date, course_completion_date, assessment_score, pass_mark, assessment_attempts, latest_assessment_status, certification_status, badge) VALUES (?, ?, ?, ?, DATE('now'), DATE('now'), ?, ?, ?, ?, ?, ?)",
						(session["user_id"], assessment_row["course_id"], session["user"], course["name"], percentage, pass_mark, attempt_count + 1, next_status, next_status, determine_badge(percentage, pass_mark))
					)
				else:
					connection.execute(
						"UPDATE course_certifications SET user_name = ?, course_name = ?, assessment_score = ?, pass_mark = ?, assessment_attempts = ?, latest_assessment_status = ?, certification_status = ?, badge = ?, course_completion_date = COALESCE(course_completion_date, DATE('now')) WHERE user_id = ? AND course_id = ?",
						(session["user"], course["name"], percentage, pass_mark, attempt_count + 1, next_status, next_status, determine_badge(percentage, pass_mark), session["user_id"], assessment_row["course_id"])
					)
				if certifiable:
					connection.execute("UPDATE course_assignments SET status = 'feedback_pending', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?", (assessment_row["course_id"], session["user_id"]))
				elif result == "fail":
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
				flash("Assessment attempt not found.", "error")
				return redirect(safe_referrer(url_for("home")))
				
			if attempt["student_id"] != session["user_id"]:
				flash("Unauthorized access to this assessment attempt.", "error")
				return redirect(safe_referrer(url_for("home")))
				
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
				flash("Assessment attempt not found.", "error")
				return redirect(safe_referrer(url_for("home")))
				
			if attempt["student_id"] != session["user_id"]:
				flash("Unauthorized access to this assessment attempt.", "error")
				return redirect(safe_referrer(url_for("home")))
				
			if attempt["result"] != "pass":
				flash("Answer review is only available for passed assessments.")
				return redirect(safe_referrer(url_for("course_detail", course_id=attempt["course_id"])))
				
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

	@app.get("/proxy/embed")
	def proxy_embed():
		"""Proxy external URLs to strip iframe-blocking headers for the embedded viewer."""
		url = request.args.get("url")
		if not url:
			return "URL is required", 400
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("SELECT id FROM courses WHERE content_url = ?", (url,)).fetchone()
			if not course or not course_is_visible(connection, course["id"], session["user_id"]):
				return "Only the content of a course you can access can be embedded.", 403
		if not is_safe_proxy_target(url):
			return "This address cannot be embedded.", 403
		
		import urllib.request
		from flask import Response
		
		try:
			req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
			with urllib.request.urlopen(req, timeout=10) as resp:
				content = resp.read()
				
				headers = {}
				for k, v in resp.getheaders():
					k_lower = k.lower()
					if k_lower not in ('x-frame-options', 'content-security-policy', 'transfer-encoding', 'content-length', 'content-encoding', 'strict-transport-security'):
						headers[k] = v
				
				if b'<head>' in content:
					content = content.replace(b'<head>', f'<head><base href="{url}">'.encode('utf-8', 'ignore'), 1)
				elif b'<head ' in content:
					content = content.replace(b'<head ', f'<head><base href="{url}"></head><head '.encode('utf-8', 'ignore'), 1)
					
				return Response(content, status=resp.status, headers=headers)
		except Exception as e:
			return f"Failed to proxy embedded page: {str(e)}", 500

	@app.get("/course/<int:course_id>")
	def course_detail(course_id):
		"""Show assigned course content and each student's completion state."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (session["user_id"], course_id,)).fetchone()
			allowed = course_is_visible(connection, course_id, session["user_id"])
			assignment = connection.execute("SELECT status, completed_at FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"])).fetchone()
			# Removed auto-assignment on course view as requested by user
			
			certification = get_user_course_record(connection, session["user_id"], course_id)
			progress = get_course_status_label(assignment["status"]) if assignment else "NOT_STARTED"
			if certification and certification["certification_status"] == "CERTIFIED":
				progress = "CERTIFIED"
			if certification and certification["latest_assessment_status"] == "FEEDBACK_PENDING":
				progress = "FEEDBACK_PENDING"
			assessments = connection.execute("SELECT * FROM assessments WHERE course_id = ? ORDER BY id", (course_id,)).fetchall()
			stats = connection.execute("""
				SELECT 
					(SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = ?) AS avg_rating,
					(SELECT COUNT(*) FROM course_certifications WHERE course_id = ? AND feedback_rating IS NOT NULL) AS rating_count,
					(SELECT COUNT(DISTINCT student_id) FROM course_assignments WHERE course_id = ?) AS enrolled_count
			""", (course_id, course_id, course_id)).fetchone()
			feedbacks = connection.execute("""
				SELECT cc.feedback_rating, cc.feedback_comments, cc.feedback_submitted_at, u.full_name as reviewer_name
				FROM course_certifications cc
				JOIN users u ON cc.user_id = u.id
				WHERE cc.course_id = ? AND cc.feedback_comments IS NOT NULL AND cc.feedback_comments != ''
				ORDER BY cc.feedback_submitted_at DESC
			""", (course_id,)).fetchall()
		if not course:
			flash("Course not found.", "error")
			return redirect(safe_referrer(url_for("home")))
		if not allowed:
			flash("You do not have permission to view this course.", "error")
			return redirect(safe_referrer(url_for("home")))
		return render_template("course.html", course=course, progress=progress, certification=certification, assessments=assessments, stats=stats, feedbacks=feedbacks, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"), impersonating=session.get("impersonator_id"))

	@app.post("/course/<int:course_id>/complete")
	def complete_course(course_id):
		"""Mark course as completed for the current student."""
		if not session.get("user_id"):
			flash("Please log in to continue.", "error")
			return redirect(safe_referrer(url_for("home")))
		if session.get("role") == "admin":
			flash("Admins cannot complete courses. Please use 'View As Student' to simulate this action.", "error")
			return redirect(safe_referrer(url_for("home")))
		with get_db() as connection:
			course = connection.execute("SELECT created_by FROM courses WHERE id = ?", (course_id,)).fetchone()
			if course and course["created_by"] == session["user_id"]:
				flash("You cannot take or participate in a course you created.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if certification and certification["certification_status"] == "CERTIFIED":
				flash("Course already certified; you can review the material and view the certificate.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
			
			assignment = connection.execute("SELECT status FROM course_assignments WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"])).fetchone()
			if not assignment:
				course = connection.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
				if course:
					connection.execute("INSERT INTO assignment_history (course_id, course_name, user_id, user_name, assignment_source, assigned_by, assigned_by_name, assignment_status, duplicate_check_result) VALUES (?, ?, ?, ?, 'Individual', ?, ?, 'assigned', 'new')", (course_id, course["name"], session["user_id"], session["user"], session["user_id"], "Self-Enrolled"))
			
			connection.execute("INSERT INTO course_assignments (course_id, student_id, status, completed_at) VALUES (?, ?, 'in_progress', CURRENT_TIMESTAMP) ON CONFLICT(course_id, student_id) DO UPDATE SET status='in_progress', completed_at=COALESCE(course_assignments.completed_at, CURRENT_TIMESTAMP)", (course_id, session["user_id"]))
		return redirect(url_for("course_detail", course_id=course_id))

	@app.route("/course/<int:course_id>/feedback", methods=["GET", "POST"])
	def feedback_form(course_id):
		"""Collect mandatory feedback and issue the certificate if valid."""
		if not session.get("user_id"):
			flash("Please log in to continue.", "error")
			return redirect(safe_referrer(url_for("home")))
		if session.get("role") == "admin":
			flash("Admins cannot submit feedback. Please use 'View As Student' to simulate this action.", "error")
			return redirect(safe_referrer(url_for("home")))
		with get_db() as connection:
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (session["user_id"], course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course:
				flash("Course not found.", "error")
				return redirect(safe_referrer(url_for("home")))
			if not course_is_visible(connection, course_id, session["user_id"]):
				flash("You do not have permission to access this course.", "error")
				return redirect(safe_referrer(url_for("home")))
			if certification and certification["certification_status"] == "CERTIFIED":
				return redirect(safe_referrer(url_for("certificate", course_id=course_id)))
			if not certification or certification["latest_assessment_status"] not in ("FEEDBACK_PENDING", "CERTIFIED"):
				return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
		if request.method == "POST":
			rating = request.form.get("rating", "").strip()
			comments = request.form.get("comments", "").strip()
			if not rating or not rating.isdigit() or not 1 <= int(rating) <= 10:
				flash("Overall rating is mandatory and must be between 1 and 10.", "error")
				return redirect(safe_referrer(url_for("feedback_form", course_id=course_id)))
			if not comments:
				flash("Feedback comments are required before the certificate can be generated.", "error")
				return redirect(safe_referrer(url_for("feedback_form", course_id=course_id)))
			with get_db() as connection:
				certification = get_user_course_record(connection, session["user_id"], course_id)
				if certification and certification["certification_status"] == "CERTIFIED":
					flash("A certificate has already been issued for this course.", "error")
					return redirect(safe_referrer(url_for("certificate", course_id=course_id)))
				# The certificate is based on the latest passing attempt of a 'post' assessment (any type if the course has no
				# post assessment), graded against that assessment's own pass mark.
				passing = connection.execute(
					"""SELECT aa.percentage, aa.score, a.pass_percentage
					   FROM assessment_attempts aa JOIN assessments a ON a.id = aa.assessment_id
					   WHERE aa.student_id = ? AND a.course_id = ? AND aa.result = 'pass'
					     AND (a.type = 'post' OR NOT EXISTS (SELECT 1 FROM assessments p WHERE p.course_id = a.course_id AND p.type = 'post'))
					   ORDER BY aa.id DESC LIMIT 1""",
					(session["user_id"], course_id),
				).fetchone()
				if not passing:
					flash("Certificate cannot be generated for a failed assessment.", "error")
					return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
				final_score = float(passing["percentage"] or 0)
				pass_mark = int_or(passing["pass_percentage"], 60)
				attempt_score = passing["score"] or 0
				certificate_id = issue_certificate(connection, session["user_id"], course_id)
				badge = determine_badge(final_score, pass_mark)
				connection.execute(
					"INSERT INTO course_certifications (user_id, course_id, user_name, course_name, course_start_date, course_completion_date, assessment_score, pass_mark, assessment_attempts, latest_assessment_status, feedback_rating, feedback_comments, feedback_submitted_at, certificate_id, certificate_generated_at, badge, certification_status) VALUES (?, ?, ?, ?, DATE('now'), DATE('now'), ?, ?, (SELECT COUNT(*) FROM assessment_attempts WHERE student_id = ? AND assessment_id IN (SELECT id FROM assessments WHERE course_id = ?)), 'CERTIFIED', ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP, ?, 'CERTIFIED') ON CONFLICT(user_id, course_id) DO UPDATE SET user_name = excluded.user_name, course_name = excluded.course_name, assessment_score = excluded.assessment_score, pass_mark = excluded.pass_mark, assessment_attempts = excluded.assessment_attempts, latest_assessment_status = 'CERTIFIED', feedback_rating = excluded.feedback_rating, feedback_comments = excluded.feedback_comments, feedback_submitted_at = CURRENT_TIMESTAMP, certificate_id = excluded.certificate_id, certificate_generated_at = CURRENT_TIMESTAMP, badge = excluded.badge, certification_status = 'CERTIFIED'",
					(session["user_id"], course_id, session["user"], course["name"], final_score, pass_mark, session["user_id"], course_id, int(rating), comments, certificate_id, badge)
				)
				try:
					create_notification(connection, session["user_id"], f"Congratulations! You've earned a certificate for '{course['name']}'.", "certificate_earned", url_for("certificate", course_id=course_id))
				except Exception:
											pass
				connection.execute("UPDATE course_assignments SET status='certified', completed_at=COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE course_id = ? AND student_id = ?", (course_id, session["user_id"]))
				
				# Reward Engine integration
				
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
			flash("Feedback submitted successfully. Your certificate and badge have been created.", "success")
			return redirect(safe_referrer(url_for("certificate", course_id=course_id)))
		return render_template("feedback.html", course=course, user=session.get("user"), certification=certification)

	@app.get("/course/<int:course_id>/certificate")
	def certificate(course_id):
		"""Display and allow a student to review or download their certificate."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (session["user_id"], course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course:
				flash("Course not found.", "error")
				return redirect(safe_referrer(url_for("home")))
			if not course_is_visible(connection, course_id, session["user_id"]):
				flash("You do not have permission to access this course.", "error")
				return redirect(safe_referrer(url_for("home")))
			if not certification or certification["certification_status"] != "CERTIFIED":
				flash("Certificate is not available until feedback is submitted and the course is certified.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
		return render_template("certificate.html", course=course, certification=certification, user=session.get("user"))

	@app.get("/course/<int:course_id>/certificate/download")
	def download_certificate(course_id):
		"""Return the certificate as a downloadable PNG image for the student."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		with get_db() as connection:
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (session["user_id"], course_id,)).fetchone()
			certification = get_user_course_record(connection, session["user_id"], course_id)
			if not course:
				flash("Course not found.", "error")
				return redirect(safe_referrer(url_for("home")))
			if not course_is_visible(connection, course_id, session["user_id"]):
				flash("You do not have permission to access this course.", "error")
				return redirect(safe_referrer(url_for("home")))
			if not certification or certification["certification_status"] != "CERTIFIED":
				flash("Certificate is not available until feedback is submitted and the course is certified.", "error")
				return redirect(safe_referrer(url_for("course_detail", course_id=course_id)))
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
				flash("No active API credentials found for this user.", "warning")
				return redirect(safe_referrer(url_for("admin_panel")))
				
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
		allowed = {"user": "users", "course": "courses", "assessment": "assessments"}
		table = allowed.get(resource)
		if not table or resource == "user" and record_id == session.get("user_id"):
			flash("This record cannot be deleted.", "error")
			return redirect(safe_referrer(url_for("admin_panel")))

		with get_db() as connection:
			if resource == "course":
				course = connection.execute("SELECT created_by, status FROM courses WHERE id = ?", (record_id,)).fetchone()
				if not course:
					flash("Course not found.", "error")
					return redirect(safe_referrer(url_for("courses_page")))
				if session.get("role") != "admin" and course["created_by"] != session.get("user_id"):
					flash("You can only delete courses you created.", "error")
					return redirect(safe_referrer(url_for("courses_page")))
				if (course["status"] or "").lower() != "draft":
					flash(f"Cannot delete a {course['status']} course. You can only delete draft courses.", "error")
					return redirect(safe_referrer(url_for("courses_page")))
			elif resource == "user" and session.get("role") != "admin":
				flash("You do not have permission to delete users.", "error")
				return redirect(safe_referrer(url_for("admin_panel")))

		try:
			with get_db() as connection:
				cursor = connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
				if cursor.rowcount:
					flash(f"{resource.title()} deleted successfully.", "success")
				else:
					flash("Record not found.", "error")
		except sqlite3.IntegrityError:
			flash("This record is still in use and cannot be deleted.", "error")
		return redirect(safe_referrer(url_for("admin_panel")))

	@app.get("/assessments/<int:assessment_id>/questions/download")
	def download_assessment_questions(assessment_id):
		"""Download assessment questions for admins or owning moderators only."""
		if session.get("role") not in ("admin", "moderator"):
			flash("You must be an admin or moderator to download assessment questions.", "error")
			return redirect(safe_referrer(url_for("home")))
		stream = question_csv(assessment_id, session["user_id"], session["role"])
		if stream is None:
			return redirect(safe_referrer(url_for("admin_panel")))
		return send_file(stream, as_attachment=True, download_name=f"assessment-{assessment_id}-questions.csv", mimetype="text/csv")


	@app.get("/courses")
	@staff_required
	def courses_page():
		"""Dedicated course management page with wizard."""
		with get_db() as connection:
			query = """SELECT c.*, u.full_name AS creator_name,
				   (SELECT ROUND(AVG(CAST(feedback_rating AS FLOAT)), 1) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS avg_rating,
				   (SELECT COUNT(*) FROM course_certifications WHERE course_id = c.id AND feedback_rating IS NOT NULL) AS rating_count
				   FROM courses c JOIN users u ON u.id = c.created_by"""
			
			role = session.get("role")
			user_id = session.get("user_id")
			
			if role == "admin":
				query += " ORDER BY c.id DESC"
				courses = connection.execute(query).fetchall()
			else:
				query += " WHERE LOWER(IFNULL(c.status, 'published')) NOT IN ('draft', 'inactive') OR c.created_by = ? ORDER BY c.id DESC"
				courses = connection.execute(query, (user_id,)).fetchall()
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
		duration_minutes = int_or(request.form.get("duration_minutes"), 0)
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
			return redirect(safe_referrer(url_for("courses_page")))

		with get_db() as connection:
			cursor = connection.execute(
				"INSERT INTO courses (name, description, category, content_type, content_url, created_by, status, tags, duration_minutes, difficulty, thumbnail_color) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
				(name, description, category, content_type, content_url, session["user_id"], status, tags, duration_minutes, difficulty, thumbnail_color)
			)
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'create', 'course', ?)",
				(session["user_id"], cursor.lastrowid)
			)
		flash(f"Course '{name}' created successfully.", "success")
		return redirect(safe_referrer(url_for("courses_page")))

	@app.post("/courses/<int:course_id>/update")
	@staff_required
	def courses_update(course_id):
		"""Inline update a course from the course list."""
		with get_db() as connection:
			if not course_is_manageable(connection, course_id, session["user_id"], session["role"]):
				flash("You can only edit courses you created.", "error")
				return redirect(safe_referrer(url_for("courses_page")))
			
			# Get existing course to check current content
			existing = connection.execute("SELECT content_url, content_type FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not existing:
				flash("Course not found.", "error")
				return redirect(safe_referrer(url_for("courses_page")))

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
					flash("Please provide a valid URL or file for publication.", "error")
					return redirect(safe_referrer(url_for("courses_page")))

			connection.execute(
				"UPDATE courses SET name=?, description=?, category=?, status=?, tags=?, duration_minutes=?, difficulty=?, thumbnail_color=?, content_type=?, content_url=? WHERE id=?",
				(
					request.form.get("name", "").strip(),
					request.form.get("description", "").strip(),
					request.form.get("category", "General").strip() or "General",
					status,
					request.form.get("tags", "").strip(),
					int_or(request.form.get("duration_minutes"), 0),
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
		flash("Course updated.", "success")
		return redirect(safe_referrer(url_for("courses_page")))

	@app.post("/courses/<int:course_id>/publish")
	@staff_required
	def courses_publish(course_id):
		"""Quick publish a course."""
		with get_db() as connection:
			if not course_is_manageable(connection, course_id, session["user_id"], session["role"]):
				flash("You can only publish courses you created.", "error")
				return redirect(safe_referrer(url_for("courses_page")))
			
			course = connection.execute("SELECT content_url, content_type FROM courses WHERE id = ?", (course_id,)).fetchone()
			if not course or course["content_url"] == "#" or not course["content_url"]:
				flash("Please upload educational material or add a URL before publishing this course.", "error")
				return redirect(safe_referrer(url_for("courses_page")))

			connection.execute("UPDATE courses SET status = 'published' WHERE id = ?", (course_id,))
			connection.execute(
				"INSERT INTO audit_logs (user_id, action, entity_type, entity_id) VALUES (?, 'publish', 'course', ?)",
				(session["user_id"], course_id)
			)
		flash("Course published successfully!", "success")
		return redirect(safe_referrer(url_for("courses_page")))


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
		session.update(user=target["full_name"], user_id=target["id"], role=target["role"], actual_role=target["role"])
		return redirect(url_for("home"))

	@app.get("/admin/exit-view")
	def exit_view():
		"""Restore the administrator after a view-as session."""
		admin_id = session.get("impersonator_id")
		if not admin_id:
			flash("You are not currently impersonating another user.", "error")
			return redirect(safe_referrer(url_for("home")))
		with get_db() as connection:
			admin = connection.execute("SELECT id, full_name, role FROM users WHERE id = ? AND role = 'admin'", (admin_id,)).fetchone()
		if not admin:
			session.clear()
			return redirect(url_for("home"))
		session.pop("impersonator_id", None)
		session.update(user=admin["full_name"], user_id=admin["id"], role=admin["role"], actual_role=admin["role"])
		return redirect(url_for("admin_panel"))

	@app.get("/uploads/<path:filename>")
	def uploaded_file(filename):
		"""Serve stored files to logged-in users; only media renders inline, everything else downloads."""
		if not session.get("user_id"):
			return redirect(url_for("home"))
		response = send_from_directory(UPLOAD_FOLDER, filename, as_attachment=not serve_inline(filename))
		response.headers["X-Content-Type-Options"] = "nosniff"
		return response

	@app.post("/switch-role")
	def switch_role():
		"""Toggle between basic user and admin view for staff."""
		if "user_id" not in session:
			return redirect(url_for("home"))
		if session.get("impersonator_id"):
			flash("Exit the view-as session before switching roles.", "error")
			return redirect(safe_referrer(url_for("home")))
		if session.get("actual_role") not in ("admin", "moderator"):
			flash("Only staff members can switch roles.", "error")
			return redirect(safe_referrer(url_for("home")))
		
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
			
			employee_id = request.form.get("employee_id", "").strip()
			department_id = request.form.get("department_id")
			department_id = int(department_id) if department_id else None
			position_id = request.form.get("position_id")
			position_id = int(position_id) if position_id else None
			location_id = request.form.get("location_id")
			location_id = int(location_id) if location_id else None
			about_me = request.form.get("about_me", "").strip()
			interests = request.form.getlist("interests")

			if not full_name or not email or not phone_number or not employee_id or not location_id:
				flash("Name, Employee ID, Email, Phone, and Location are mandatory.", "error")
				return redirect(safe_referrer(url_for("profile")))
				
			with get_db() as connection:
				dup = connection.execute("SELECT id, employee_id, email FROM users WHERE (employee_id = ? OR email = ?) AND id != ?", (employee_id, email, session["user_id"])).fetchone()
				if dup:
					if dup["employee_id"] == employee_id: flash("Employee ID already in use.", "error")
					else: flash("Email already in use.", "error")
					return redirect(safe_referrer(url_for("profile")))
					
				if pic and pic.filename:
					ext = os.path.splitext(pic.filename)[1].lower()
					if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
						flash("Profile picture must be a PNG, JPG, GIF or WebP image.", "error")
						return redirect(safe_referrer(url_for("profile")))
					pic_filename = uuid4().hex + ext
					pic.save(os.path.join(UPLOAD_FOLDER, pic_filename))
				connection.execute(
					"UPDATE users SET full_name = ?, email = ?, phone_number = ?, employee_id = ?, department_id = ?, position_id = ?, location_id = ?, about_me = ?, profile_picture = ? WHERE id = ?",
					(full_name, email, phone_number, employee_id, department_id, position_id, location_id, about_me, pic_filename, session["user_id"])
				)

					
			session["user"] = full_name
			session["profile_picture"] = pic_filename
			flash("Profile updated successfully.", "success")
			return redirect(safe_referrer(url_for("profile")))
			
		with get_db() as connection:
			user_data = connection.execute("SELECT u.*, COALESCE(GROUP_CONCAT(ui.interest_id), '') AS interest_ids FROM users u LEFT JOIN user_interest ui ON ui.user_id = u.id WHERE u.id = ? GROUP BY u.id", (session["user_id"],)).fetchone()
			master_depts = connection.execute("SELECT department_id as id, department_name as name FROM departments WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY department_name").fetchall()
			master_positions = connection.execute("SELECT id, name FROM positions WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name").fetchall()
			master_interests = connection.execute("SELECT id, interest_name as name FROM interest_master WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY name").fetchall()
			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY location_name").fetchall()
		return render_template("profile.html", user_data=user_data, master_depts=master_depts, master_positions=master_positions, master_interests=master_interests, master_locations=master_locations, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

	@app.context_processor
	def inject_notifications():
		unread = 0
		active_release = None
		if session.get("user_id"):
			try:
				with get_db() as connection:
					count = connection.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (session["user_id"],)).fetchone()["n"]
					unread = count
			except Exception:
				pass
		try:
			with get_db() as connection:
				active_release = connection.execute("SELECT * FROM app_releases WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
		except Exception:
			pass
		return {"unread_notifications_count": unread, "active_release": active_release}

	def create_notification(connection, user_id, message, type_name="system", target_url="#"):
		connection.execute(
			"INSERT INTO notifications (user_id, message, type, target_url) VALUES (?, ?, ?, ?)",
			(user_id, message, type_name, target_url)
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
			description = sanitize_html(request.form.get("description", "").strip())
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
						if not attachment_allowed(file.filename):
							flash(f"Skipped attachment '{file.filename}': file type not allowed.", "error")
							continue
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
						create_notification(connection, r["id"], f"New content '{title}' is waiting for approval.", "pending_review", url_for("approval_queue"))
						
			flash("Post created successfully!", "success")
			return redirect(safe_referrer(url_for("my_posts")))
			
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
			flash("Post not found.", "error")
			return redirect(safe_referrer(url_for("my_posts")))
			
		if post["created_by"] != user_id and role != "admin":
			flash("Unauthorized to edit this post.", "error")
			return redirect(safe_referrer(url_for("my_posts")))
			
		with get_db() as connection:
			attachments = connection.execute("SELECT * FROM post_attachments WHERE post_id = ?", (post_id,)).fetchall()
			approval_history = connection.execute('''SELECT h.*, u.full_name as reviewer_name 
			                                         FROM post_approval_history h 
			                                         LEFT JOIN users u ON h.reviewed_by = u.id 
			                                         WHERE h.post_id = ? AND h.action IN ('APPROVE', 'REJECT', 'REQUEST_CHANGES') 
			                                         ORDER BY h.id DESC''', (post_id,)).fetchall()
			
		if request.method == "POST":
			title = request.form.get("title", "").strip()
			description = sanitize_html(request.form.get("description", "").strip())
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
						if not attachment_allowed(file.filename):
							flash(f"Skipped attachment '{file.filename}': file type not allowed.", "error")
							continue
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
					create_notification(connection, user_id, f"Your post '{title}' requires approval after modification.", "re_approval_needed", url_for("my_posts"))
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"Modified post '{title}' (previously published) is waiting for approval.", "pending_review", url_for("approval_queue"))
				elif new_status == "PENDING_APPROVAL" and old_status != "PENDING_APPROVAL":
					reviewers = connection.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
					for r in reviewers:
						create_notification(connection, r["id"], f"Post '{title}' is waiting for approval.", "pending_review", url_for("approval_queue"))
						
			flash("Post updated successfully!", "success")
			return redirect(safe_referrer(url_for("my_posts")))
			
		return render_template("edit_post.html", post=post, attachments=attachments, approval_history=approval_history, role=role, user=session.get("user"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

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
						  (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.id) AS comment_count,
						  (SELECT comments FROM post_approval_history h WHERE h.post_id = p.id AND h.action IN ('APPROVE', 'REJECT', 'REQUEST_CHANGES') ORDER BY h.id DESC LIMIT 1) AS latest_review_comment
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
			flash("Post not found.", "error")
			return redirect(safe_referrer(url_for("my_posts")))
			
		is_owner = post["created_by"] == user_id
		if role == "basic user":
			if not is_owner:
				flash("You can only inactivate your own posts.", "error")
				return redirect(safe_referrer(url_for("my_posts")))
		elif role != "admin" and not is_owner:
			flash("Unauthorized to inactivate this post.", "error")
			return redirect(safe_referrer(url_for("my_posts")))
			
		with get_db() as connection:
			connection.execute("UPDATE posts SET status = 'INACTIVE' WHERE id = ?", (post_id,))
			
		flash("Post inactivated and removed from public forum.", "success")
		return redirect(safe_referrer(url_for("my_posts")))

	@app.get("/community/approval-queue")
	def approval_queue():
		if "user_id" not in session:
			return redirect(url_for("home"))
		if session.get("role") not in ("admin", "moderator"):
			flash("You must be an admin or moderator to access the approval queue.", "error")
			return redirect(safe_referrer(url_for("home")))
			
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

	@app.route("/community/approval-queue/<int:post_id>/action", methods=["GET", "POST"])
	def approval_action(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
		if session.get("role") not in ("admin", "moderator"):
			flash("You do not have permission to review community content.", "error")
			return redirect(safe_referrer(url_for("home")))
			
		if request.method == "GET":
			return redirect(safe_referrer(url_for("approval_queue")))
			
		reviewer_id = session.get("user_id")
		action = request.form.get("action")
		comments = request.form.get("comments", "").strip()
		
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			
		if not post:
			flash("Post not found.", "error")
			return redirect(safe_referrer(url_for("approval_queue")))
			
		if post["created_by"] == reviewer_id:
			flash("You cannot review your own post.", "error")
			return redirect(safe_referrer(url_for("approval_queue")))
		if post["status"] not in ("PENDING_APPROVAL", "UNPUBLISHED"):
			flash("This post is not awaiting review.", "error")
			return redirect(safe_referrer(url_for("approval_queue")))

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
			flash("Invalid action.", "error")
			return redirect(safe_referrer(url_for("approval_queue")))
			
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
			
			create_notification(connection, post["created_by"], notif_message, notif_type, url_for("post_detail", post_id=post_id))
			
		flash(f"Decision '{action}' submitted successfully!", "success")
		return redirect(safe_referrer(url_for("approval_queue")))

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
			flash("Post not found.", "error")
			return redirect(safe_referrer(url_for("community_feed")))
			
		is_creator = post["created_by"] == user_id
		is_reviewer = role in ("admin", "moderator")
		if post["status"] != "PUBLISHED" and not (is_creator or is_reviewer):
			flash("Unauthorized to view this post.", "error")
			return redirect(safe_referrer(url_for("community_feed")))
			
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
			flash("Invalid rating. Must be between 1 and 5.", "error")
			return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))
			
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				flash("Post not found.", "error")
				return redirect(safe_referrer(url_for("community_feed")))
				
			if post["created_by"] == user_id:
				flash("You cannot rate your own post.", "error")
				return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))
				
			if post["status"] != "PUBLISHED":
				flash("Only published posts can be rated.", "success")
				return redirect(safe_referrer(url_for("community_feed")))
				
			existing = connection.execute("SELECT id FROM post_ratings WHERE post_id = ? AND user_id = ?", (post_id, user_id)).fetchone()
			if existing:
				flash("You have already rated this post. Your rating cannot be changed.", "error")
				return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))
				
			connection.execute(
				"""INSERT INTO post_ratings (post_id, user_id, rating, updated_at)
				   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
				   ON CONFLICT(post_id, user_id) DO UPDATE SET rating = excluded.rating, updated_at = CURRENT_TIMESTAMP""",
				(post_id, user_id, rating)
			)
			try:
				_post = connection.execute("SELECT created_by, title FROM posts WHERE id=?", (post_id,)).fetchone()
				if _post and _post["created_by"] != user_id:
					create_notification(connection, _post["created_by"], f"Someone rated your post '{_post['title']}'", "post_interaction", url_for("post_detail", post_id=post_id))
			except Exception:
											pass
			
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
			
		flash("Thank you for your rating!", "success")
		return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))

	@app.post("/community/post/<int:post_id>/comment")
	def comment_post(post_id):
		if "user_id" not in session:
			return redirect(url_for("home"))
			
		user_id = session.get("user_id")
		comment_text = request.form.get("comment_text", "").strip()
		
		if not comment_text:
			flash("Comment cannot be empty.", "error")
			return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))
			
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				flash("Post not found.", "error")
				return redirect(safe_referrer(url_for("community_feed")))
				
			role = session.get("role")
			if post["status"] != "PUBLISHED" and not (post["created_by"] == user_id or role in ("admin", "moderator")):
				flash("Unauthorized to comment on this post.", "error")
				return redirect(safe_referrer(url_for("community_feed")))
				
			connection.execute(
				"""INSERT INTO post_comments (post_id, user_id, comment_text)
				   VALUES (?, ?, ?)""",
				(post_id, user_id, comment_text)
			)
			try:
				_post = connection.execute("SELECT created_by, title FROM posts WHERE id=?", (post_id,)).fetchone()
				if _post and _post["created_by"] != user_id:
					create_notification(connection, _post["created_by"], f"Someone commented on your post '{_post['title']}'", "post_interaction", url_for("post_detail", post_id=post_id))
			except Exception:
											pass
			
		flash("Comment submitted successfully!", "success")
		return redirect(safe_referrer(url_for("post_detail", post_id=post_id)))

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
			all_students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user'").fetchall()
			
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
			flash("Invalid multiplier or fixed points value.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
		if status not in ("active", "inactive") or calc_type not in ("MULTIPLIER", "FIXED"):
			flash("Invalid status or calculation type.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
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
			
		flash(f"Reward source '{name}' updated successfully.", "success")
		return redirect(safe_referrer(url_for("admin_rewards")))

	@app.post("/admin/rewards/settle")
	@admin_required
	def admin_settle_rewards():
		user_id = request.form.get("user_id", type=int)
		if user_id is None:
			flash("Select a user.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
		points = request.form.get("points", 0)
		remarks = request.form.get("remarks", "Settle points").strip()
		
		try:
			points = int(points)
		except ValueError:
			flash("Points must be an integer.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
		if points <= 0:
			flash("Settlement points must be greater than zero.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
		with get_db() as connection:
			wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
			if not wallet or wallet["current_balance"] < points:
				flash("Insufficient points balance for settlement.", "error")
				return redirect(safe_referrer(url_for("admin_rewards")))
				
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
			
		flash(f"Successfully settled {points} points for user.", "success")
		return redirect(safe_referrer(url_for("admin_rewards")))

	@app.post("/admin/rewards/reset")
	@admin_required
	def admin_reset_rewards():
		user_id = request.form.get("user_id")
		confirm = request.form.get("confirm")
		if user_id != "all":
			try:
				user_id = int(user_id)
			except (TypeError, ValueError):
				flash("Select a user.", "error")
				return redirect(safe_referrer(url_for("admin_rewards")))
		
		if confirm != "YES":
			flash("Please confirm the warning checkboxes to execute a reset.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
		with get_db() as connection:
			if user_id == "all":
				active_wallets = connection.execute("SELECT * FROM user_wallets WHERE current_balance > 0").fetchall()
				if not active_wallets:
					flash("No active wallets with positive balances to reset.", "warning")
					return redirect(safe_referrer(url_for("admin_rewards")))
					
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
				flash("Successfully executed a global reset of points for all users.", "success")
				
			else:
				wallet = connection.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
				if not wallet or wallet["current_balance"] <= 0:
					flash("User has no points balance to reset.", "error")
					return redirect(safe_referrer(url_for("admin_rewards")))
					
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
				flash(f"Successfully reset reward points to 0 for user.", "success")
				
		return redirect(safe_referrer(url_for("admin_rewards")))

	@app.post("/admin/rewards/adjust")
	@admin_required
	def admin_adjust_rewards():
		user_id = request.form.get("user_id", type=int)
		if user_id is None:
			flash("Select a user.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
		points = request.form.get("points", 0)
		remarks = request.form.get("remarks", "Manual adjustment").strip()
		
		try:
			points = int(points)
		except ValueError:
			flash("Adjustment points must be a non-zero integer.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
		if points == 0:
			flash("Adjustment points cannot be zero.", "error")
			return redirect(safe_referrer(url_for("admin_rewards")))
			
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
				flash("Adjustment cannot result in a negative wallet balance.", "error")
				return redirect(safe_referrer(url_for("admin_rewards")))
				
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
			
		flash(f"Successfully adjusted user balance by {points:+} points.", "success")
		return redirect(safe_referrer(url_for("admin_rewards")))

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

	@app.post("/logout")
	def logout():
		"""End the current session."""
		session.clear()
		return redirect(url_for("home"))

	# â”€â”€ API v1 Authentication & Routing Block â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


	@app.get("/api/interests")
	def get_interests():
		search = request.args.get("search", "").strip()
		with get_db() as conn:
			if search:
				query = "SELECT id, interest_name as name FROM interest_master WHERE LOWER(COALESCE(status, 'active')) = 'active' AND interest_name LIKE ? ORDER BY interest_name"
				rows = conn.execute(query, (f"%{search}%",)).fetchall()
			else:
				rows = conn.execute("SELECT id, interest_name as name FROM interest_master WHERE LOWER(COALESCE(status, 'active')) = 'active' ORDER BY interest_name").fetchall()
		return jsonify([dict(r) for r in rows])

	@app.post("/api/interests")
	def create_interest():
		data = request.get_json(silent=True) or {}
		name = (data.get("interest_name") or "").strip()
		if not name:
			return {"error": "Interest name is required."}, 400
		
		if not session.get("user_id"):
			return {"error": "Login required."}, 401
		normalized = " ".join(name.lower().split())
		user_id = session["user_id"]
		
		with get_db() as conn:
			existing = conn.execute("SELECT id, interest_name as name FROM interest_master WHERE normalized_name = ?", (normalized,)).fetchone()
			if existing:
				return jsonify(dict(existing)), 200
			
			try:
				interest_id = conn.execute(
					"INSERT INTO interest_master (interest_name, normalized_name, created_by) VALUES (?, ?, ?)",
					(name, normalized, user_id)
				).lastrowid
				return jsonify({"id": interest_id, "name": name}), 201
			except sqlite3.IntegrityError:
				# Rare race condition
				existing = conn.execute("SELECT id, interest_name as name FROM interest_master WHERE normalized_name = ?", (normalized,)).fetchone()
				return jsonify(dict(existing)), 200

	@app.get("/api/users/<int:target_user_id>/interests")
	def get_user_interests(target_user_id):
		if not session.get("user_id"):
			return {"error": "Login required."}, 401
		with get_db() as conn:
			rows = conn.execute("""
				SELECT i.id, i.interest_name as name 
				FROM user_interest ui
				JOIN interest_master i ON ui.interest_id = i.id
				WHERE ui.user_id = ?
			""", (target_user_id,)).fetchall()
		return jsonify([dict(r) for r in rows])

	@app.post("/api/users/<int:target_user_id>/interests")
	def add_user_interest(target_user_id):
		if session.get("user_id") != target_user_id and session.get("role") != "admin":
			return {"error": "Unauthorized"}, 403
			
		data = request.get_json(silent=True) or {}
		interest_id = data.get("interest_id")
		if not interest_id:
			return {"error": "interest_id is required."}, 400
			
		with get_db() as conn:
			try:
				conn.execute("INSERT INTO user_interest (user_id, interest_id) VALUES (?, ?)", (target_user_id, interest_id))
			except sqlite3.IntegrityError:
				pass # already exists
		return {"message": "Interest added to user."}, 200

	@app.delete("/api/users/<int:target_user_id>/interests/<int:interest_id>")
	def delete_user_interest(target_user_id, interest_id):
		if session.get("user_id") != target_user_id and session.get("role") != "admin":
			return {"error": "Unauthorized"}, 403
			
		with get_db() as conn:
			conn.execute("DELETE FROM user_interest WHERE user_id = ? AND interest_id = ?", (target_user_id, interest_id))
		return {"message": "Interest removed."}, 200

	@app.get("/api/v1/docs")
	@admin_required
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

	
	
	# --- SERVER-SIDE PAGINATION & SEARCH ADMIN APIS ---
	@app.get("/api/admin/users")
	def get_admin_users_api():
		if not session.get("user_id") or session.get("role") != "admin":
			return jsonify({"error": "Unauthorized"}), 403
			
		page = max(1, request.args.get("page", 1, type=int))
		page_size = 15
		offset = (page - 1) * page_size
		search = request.args.get("search", "").strip().lower()
		role_filter = request.args.get("role", "").strip().lower()

		where_clauses = []
		params = []

		if search:
			where_clauses.append("(LOWER(u.full_name) LIKE ? OR LOWER(u.username) LIKE ? OR LOWER(COALESCE(u.email,'')) LIKE ? OR LOWER(COALESCE(u.employee_id,'')) LIKE ? OR LOWER(u.role) LIKE ? OR LOWER(COALESCE(ca.course_id,'')) LIKE ?)")
			s_pat = f"%{search}%"
			params.extend([s_pat, s_pat, s_pat, s_pat, s_pat, s_pat])

		if role_filter:
			where_clauses.append("LOWER(u.role) LIKE ?")
			params.append(f"%{role_filter}%")

		where_str = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

		with get_db() as conn:
			count_sql = f"SELECT COUNT(DISTINCT u.id) AS total FROM users u LEFT JOIN course_assignments ca ON ca.student_id = u.id {where_str}"
			total_records = conn.execute(count_sql, params).fetchone()["total"]

			data_sql = f"""
				SELECT u.id, u.full_name, u.username, u.role, u.employee_id, u.email, u.phone_number, u.department_id, u.position_id, u.location_id, u.about_me,
				       COALESCE(GROUP_CONCAT(DISTINCT ca.course_id), '') AS course_ids,
					   COALESCE(GROUP_CONCAT(DISTINCT ui.interest_id), '') AS interest_ids
				FROM users u
				LEFT JOIN course_assignments ca ON ca.student_id = u.id
				LEFT JOIN user_interest ui ON ui.user_id = u.id
				{where_str}
				GROUP BY u.id
				ORDER BY u.id DESC
				LIMIT ? OFFSET ?
			"""
			data_params = params + [page_size, offset]
			rows = conn.execute(data_sql, data_params).fetchall()
			
			import math
			total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

			return jsonify({
				"data": [dict(r) for r in rows],
				"pagination": {
					"page": page,
					"pageSize": page_size,
					"totalRecords": total_records,
					"totalPages": total_pages
				}
			})


	@app.get("/api/admin/courses")
	def get_admin_courses_api():
		if not session.get("user_id") or session.get("role") != "admin":
			return jsonify({"error": "Unauthorized"}), 403

		page = max(1, request.args.get("page", 1, type=int))
		page_size = 15
		offset = (page - 1) * page_size
		search = request.args.get("search", "").strip().lower()
		status_filter = request.args.get("status", "").strip().lower()

		where_clauses = []
		params = []

		if search:
			where_clauses.append("(CAST(c.id AS TEXT) LIKE ? OR LOWER(c.name) LIKE ? OR LOWER(COALESCE(c.category,'general')) LIKE ? OR LOWER(COALESCE(c.content_type,'')) LIKE ? OR LOWER(COALESCE(c.status,'published')) LIKE ?)")
			s_pat = f"%{search}%"
			params.extend([s_pat, s_pat, s_pat, s_pat, s_pat])

		if status_filter:
			where_clauses.append("LOWER(COALESCE(c.status, 'published')) = ?")
			params.append(status_filter)

		where_str = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

		with get_db() as conn:
			count_sql = f"SELECT COUNT(*) AS total FROM courses c {where_str}"
			total_records = conn.execute(count_sql, params).fetchone()["total"]

			data_sql = f"""
				SELECT c.*, u.full_name AS creator 
				FROM courses c 
				LEFT JOIN users u ON u.id = c.created_by 
				{where_str}
				ORDER BY c.id DESC
				LIMIT ? OFFSET ?
			"""
			rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

			import math
			total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

			return jsonify({
				"data": [dict(r) for r in rows],
				"pagination": {
					"page": page,
					"pageSize": page_size,
					"totalRecords": total_records,
					"totalPages": total_pages
				}
			})


	@app.get("/api/admin/api-credentials")
	def get_admin_api_credentials_api():
		if not session.get("user_id") or session.get("role") != "admin":
			return jsonify({"error": "Unauthorized"}), 403

		page = max(1, request.args.get("page", 1, type=int))
		page_size = 15
		offset = (page - 1) * page_size
		search = request.args.get("search", "").strip().lower()

		where_clauses = []
		params = []

		if search:
			where_clauses.append("(LOWER(ac.api_key) LIKE ? OR LOWER(u.username) LIKE ? OR LOWER(u.full_name) LIKE ? OR LOWER(u.role) LIKE ? OR LOWER(ac.status) LIKE ?)")
			s_pat = f"%{search}%"
			params.extend([s_pat, s_pat, s_pat, s_pat, s_pat])

		where_str = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

		with get_db() as conn:
			count_sql = f"SELECT COUNT(*) AS total FROM api_credentials ac JOIN users u ON u.id = ac.user_id {where_str}"
			total_records = conn.execute(count_sql, params).fetchone()["total"]

			data_sql = f"""
				SELECT ac.*, u.username, u.full_name, u.role 
				FROM api_credentials ac 
				JOIN users u ON u.id = ac.user_id 
				{where_str}
				ORDER BY ac.id DESC
				LIMIT ? OFFSET ?
			"""
			rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

			import math
			total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

			return jsonify({
				"data": [dict(r) for r in rows],
				"pagination": {
					"page": page,
					"pageSize": page_size,
					"totalRecords": total_records,
					"totalPages": total_pages
				}
			})


	@app.get("/api/admin/assessments")
	def get_admin_assessments_api():
		if not session.get("user_id") or session.get("role") != "admin":
			return jsonify({"error": "Unauthorized"}), 403

		page = max(1, request.args.get("page", 1, type=int))
		page_size = 15
		offset = (page - 1) * page_size
		search = request.args.get("search", "").strip().lower()
		type_filter = request.args.get("type", "").strip().lower()

		where_clauses = []
		params = []

		if search:
			where_clauses.append("(CAST(a.id AS TEXT) LIKE ? OR LOWER(a.title) LIKE ? OR LOWER(COALESCE(c.name,'')) LIKE ? OR LOWER(a.type) LIKE ?)")
			s_pat = f"%{search}%"
			params.extend([s_pat, s_pat, s_pat, s_pat])

		if type_filter:
			where_clauses.append("LOWER(a.type) LIKE ?")
			params.append(f"%{type_filter}%")

		where_str = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

		with get_db() as conn:
			count_sql = f"SELECT COUNT(*) AS total FROM assessments a LEFT JOIN courses c ON c.id = a.course_id {where_str}"
			total_records = conn.execute(count_sql, params).fetchone()["total"]

			data_sql = f"""
				SELECT a.id, a.title, a.type, a.course_id, a.pass_percentage, a.max_attempts, c.name AS course_name 
				FROM assessments a 
				LEFT JOIN courses c ON c.id = a.course_id 
				{where_str}
				ORDER BY a.id DESC
				LIMIT ? OFFSET ?
			"""
			rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

			import math
			total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

			return jsonify({
				"data": [dict(r) for r in rows],
				"pagination": {
					"page": page,
					"pageSize": page_size,
					"totalRecords": total_records,
					"totalPages": total_pages
				}
			})


	@app.get('/api/departments')
	@app.get('/api/v1/departments')
	def get_departments_api():
		"""Return active Department Master list for dynamic dropdowns."""
		with get_db() as conn:
			depts = conn.execute("""
				SELECT department_id AS id, department_name 
				FROM departments 
				WHERE LOWER(COALESCE(status, 'active')) = 'active' 
				ORDER BY department_name
			""").fetchall()
			return jsonify([{"id": d["id"], "department_name": d["department_name"]} for d in depts])


	@app.route('/api/v1/releases/active', methods=['GET'])
	def get_active_release():
		with get_db() as conn:
			release = conn.execute("SELECT * FROM app_releases WHERE is_active = 1 LIMIT 1").fetchone()
			if release:
				import json
				def parse_json(val):
					if not val: return []
					try: return json.loads(val)
					except: return [val]
				return jsonify({
					"id": release["id"],
					"version_number": release["version_number"],
					"release_title": release["release_title"],
					"release_date": release["release_date"],
					"features": parse_json(release["features"]),
					"improvements": parse_json(release["improvements"]),
					"bug_fixes": parse_json(release["bug_fixes"])
				})
			return jsonify({"error": "No active release found"}), 404

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
		data = request.get_json(silent=True) or {}
		username = (data.get("username") or "").strip().lower()
		full_name = (data.get("full_name") or "").strip()
		password = data.get("password")
		role = data.get("role", "basic user").strip()
		
		missing = []
		if not username: missing.append("username")
		if not full_name: missing.append("full_name")
		if not password: missing.append("password")
		
		if missing:
			return {"error": f"Missing required fields: {', '.join(missing)}."}, 400
			
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
					"INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
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
		data = request.get_json(silent=True) or {}
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
				courses = connection.execute("SELECT c.*, u.full_name AS creator FROM courses c JOIN users u ON u.id = c.created_by WHERE LOWER(c.status) = 'published' OR c.created_by = ? OR c.id IN (SELECT course_id FROM course_assignments WHERE student_id = ?) ORDER BY c.id DESC", (g.api_user["id"], g.api_user["id"])).fetchall()
		return {"courses": [dict(c) for c in courses]}

	@app.post("/api/v1/courses")
	@api_staff_required
	def api_create_course():
		"""Create a new course."""
		from flask import g
		data = request.get_json(silent=True) or {}
		name = (data.get("name") or "").strip()
		description = (data.get("description") or "").strip()
		category = (data.get("category") or "General").strip()
		content_type = (data.get("content_type") or "Text/Article").strip()
		content_url = (data.get("content_url") or "").strip()
		status = (data.get("status") or "draft").strip().lower()
		
		if not name:
			return {"error": "Missing required field: name."}, 400
		if content_type not in ("URL", "PDF", "Video", "PPT"):
			return {"error": "Invalid content type. Must be one of: URL, PDF, Video, PPT."}, 400
		if status not in ("draft", "published"):
			return {"error": "Invalid status. Must be draft or published."}, 400
			
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
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (g.api_user["id"], course_id,)).fetchone()
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
		data = request.get_json(silent=True) or {}
		student_id = data.get("student_id")
		if not student_id:
			return {"error": "Missing student_id in request body."}, 400
			
		with get_db() as connection:
			course = connection.execute("""
				SELECT c.*, u.full_name as creator_name,
				       (SELECT assigned_by_name FROM assignment_history ah WHERE ah.course_id = c.id AND ah.user_id = ? ORDER BY ah.assigned_at DESC LIMIT 1) AS assigned_by
				FROM courses c
				LEFT JOIN users u ON c.created_by = u.id
				WHERE c.id = ?
			""", (g.api_user["id"], course_id,)).fetchone()
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
				if student_id != getattr(g, "api_user", {}).get("id"):
					try:
						_c_name = connection.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()["name"]
						create_notification(connection, student_id, f"You have been assigned a new course: {_c_name}", "course_assigned", f"/course/{course_id}")
					except Exception:
											pass
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
		data = request.get_json(silent=True) or {}
		title = (data.get("title") or "").strip()
		description = sanitize_html((data.get("description") or "").strip())
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
						create_notification(connection, r["id"], f"New content '{title}' is waiting for approval.", "pending_review", url_for("approval_queue"))
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
			if post["status"] != "PUBLISHED" and post["created_by"] != g.api_user["id"] and g.api_user["role"] not in ("admin", "moderator"):
				return {"error": "Access forbidden: this post is not published."}, 403
				
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
		data = request.get_json(silent=True) or {}
		rating = int_or(data.get("rating"), 0)
		if not 1 <= rating <= 5:
			return {"error": "Rating must be an integer between 1 and 5."}, 400
		
		with get_db() as connection:
			post = connection.execute("SELECT created_by, status FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				return {"error": "Post not found."}, 404
			if post["status"] != "PUBLISHED":
				return {"error": "Only published posts can be rated."}, 400
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
				try:
					_post = connection.execute("SELECT created_by, title FROM posts WHERE id=?", (post_id,)).fetchone()
					if _post and _post["created_by"] != g.api_user["id"]:
						create_notification(connection, _post["created_by"], f"Someone rated your post '{_post['title']}'", "post_interaction", f"/community/post/{post_id}")
				except Exception:
											pass
				
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
		data = request.get_json(silent=True) or {}
		comment_text = (data.get("comment") or "").strip()
		if not comment_text:
			return {"error": "Missing comment text in request body."}, 400
			
		with get_db() as connection:
			post = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
			if not post:
				return {"error": "Post not found."}, 404
			if post["status"] != "PUBLISHED" and post["created_by"] != g.api_user["id"] and g.api_user["role"] not in ("admin", "moderator"):
				return {"error": "Access forbidden: this post is not published."}, 403
			try:
				comment_id = connection.execute(
					"INSERT INTO post_comments (post_id, user_id, comment_text) VALUES (?, ?, ?)",
					(post_id, g.api_user["id"], comment_text)
				).lastrowid
				try:
					_post = connection.execute("SELECT created_by, title FROM posts WHERE id=?", (post_id,)).fetchone()
					if _post and _post["created_by"] != g.api_user["id"]:
						create_notification(connection, _post["created_by"], f"Someone commented on your post '{_post['title']}'", "post_interaction", f"/community/post/{post_id}")
				except Exception:
											pass
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
		data = request.get_json(silent=True) or {}
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
			if g.api_user["role"] == "basic user" and not user_has_course_access(connection, g.api_user["id"], assessment["course_id"]):
				return {"error": "Access forbidden: you are not assigned to this course."}, 403
				
			prior_attempts = connection.execute(
				"SELECT COUNT(*) as count FROM assessment_attempts WHERE assessment_id = ? AND student_id = ?",
				(assessment_id, g.api_user["id"])
			).fetchone()
			attempt_no = (prior_attempts["count"] or 0) + 1
			
			if attempt_no > int_or(assessment["max_attempts"], 1):
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
			pass_mark = int_or(assessment["pass_percentage"], 60)
			result = "pass" if percentage >= pass_mark else "fail"
			
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
					certificate_id = issue_certificate(connection, g.api_user["id"], assessment["course_id"])
					badge = determine_badge(percentage, pass_mark)
					connection.execute(
						"""INSERT INTO course_certifications (user_id, course_id, user_name, course_name, course_start_date, course_completion_date, assessment_score, pass_mark, assessment_attempts, latest_assessment_status, certificate_id, certificate_generated_at, badge, certification_status)
						   VALUES (?, ?, ?, ?, DATE('now'), DATE('now'), ?, ?, ?, 'CERTIFIED', ?, CURRENT_TIMESTAMP, ?, 'CERTIFIED')
						   ON CONFLICT(user_id, course_id) DO UPDATE SET assessment_score = excluded.assessment_score, pass_mark = excluded.pass_mark, assessment_attempts = excluded.assessment_attempts, latest_assessment_status = 'CERTIFIED', certificate_id = excluded.certificate_id, certificate_generated_at = CURRENT_TIMESTAMP, badge = excluded.badge, certification_status = 'CERTIFIED'""",
						(g.api_user["id"], assessment["course_id"], g.api_user["full_name"], assessment["course_name"], percentage, pass_mark, attempt_no, certificate_id, badge),
					)
					
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
				FROM user_wallets w JOIN users u ON u.id = w.user_id 
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
		data = request.get_json(silent=True) or {}
		target_user_id = data.get("target_user_id")
		points = data.get("points")
		try:
			points = int(points)
		except (TypeError, ValueError):
			return {"error": "points must be an integer."}, 400
		if not target_user_id or points <= 0:
			return {"error": "Missing or invalid target_user_id or positive points parameter."}, 400
		
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
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by, settlement_id)
					   VALUES (?, 'MANUAL_SETTLEMENT', ?, 'ADMIN_SETTLEMENT', 'Points settled by Administrator', ?, 'SETTLEMENT', ?, ?, ?, ?)""",
					(target_user_id, ref_id, -points, balance, balance - points, g.api_user["id"], ref_id)
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
		data = request.get_json(silent=True) or {}
		target_user_id = data.get("target_user_id")
		points = data.get("points")
		description = (data.get("description") or "Balance manual adjustment by Administrator").strip()
		
		try:
			points = int(points)
		except (TypeError, ValueError):
			return {"error": "points must be an integer."}, 400
		if not target_user_id:
			return {"error": "Missing target_user_id parameter."}, 400
		if points == 0:
			return {"error": "points must be a non-zero integer."}, 400
		
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
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
					   VALUES (?, 'MANUAL_ADJUSTMENT', ?, 'ADMIN_ADJUSTMENT', ?, ?, ?, ?, ?, ?)""",
					(target_user_id, ref_id, description, points, "ADJUSTMENT" if points > 0 else "REVERSAL", balance, new_balance, g.api_user["id"])
				)
				connection.execute(
					"UPDATE user_wallets SET current_balance = ?, total_adjusted = total_adjusted + ? WHERE user_id = ?",
					(new_balance, abs(points), target_user_id)
				)
			except Exception as e:
				return {"error": f"Adjustment failed: {str(e)}"}, 500
		return {"message": "Rewards adjusted successfully.", "new_balance": new_balance}, 200

	@app.post("/api/v1/rewards/reset")
	@api_admin_required
	def api_reset_rewards():
		"""Reset user reward balance to zero."""
		data = request.get_json(silent=True) or {}
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
					"""INSERT INTO reward_transactions (user_id, reward_source, source_reference_id, source_reference_type, description, points, transaction_type, balance_before, balance_after, created_by)
					   VALUES (?, 'USER_RESET', ?, 'ADMIN_RESET', 'Rewards wallet reset to zero by Administrator', ?, 'ADJUSTMENT', ?, 0, ?)""",
					(target_user_id, ref_id, -balance, balance, g.api_user["id"])
				)
				connection.execute(
					"UPDATE user_wallets SET current_balance = 0, total_adjusted = total_adjusted + ? WHERE user_id = ?",
					(balance, target_user_id)
				)
			except Exception as e:
				return {"error": f"Reset operation failed: {str(e)}"}, 500
		return {"message": "Rewards balance reset to zero successfully."}, 200

	@app.route("/admin/masters", methods=["GET", "POST"])
	@admin_required
	def master_management():
	    if request.method == "POST":
	        action = request.form.get("action")
	        user_id = session.get("user_id")
	        with get_db() as conn:
	            try:
	                if action == "add_department":
	                    name = request.form.get("department_name", "").strip()
	                    code = request.form.get("department_code", "").strip()
	                    desc = request.form.get("description", "").strip()
	                    status = request.form.get("status", "Active")
	                    if not name or not code:
	                        flash("Department Name and Code are mandatory.", "error")
	                    else:
	                        conn.execute("INSERT INTO departments (department_name, department_code, description, status, created_by) VALUES (?, ?, ?, ?, ?)", (name, code, desc, status, user_id))
	                        flash("Department created successfully.", "success")
	                        
	                elif action == "edit_department":
	                    dept_id = request.form.get("record_id")
	                    name = request.form.get("department_name", "").strip()
	                    code = request.form.get("department_code", "").strip()
	                    desc = request.form.get("description", "").strip()
	                    status = request.form.get("status", "Active")
	                    if not name or not code:
	                        flash("Department Name and Code are mandatory.", "error")
	                    else:
	                        conn.execute("UPDATE departments SET department_name = ?, department_code = ?, description = ?, status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE department_id = ?", (name, code, desc, status, user_id, dept_id))
	                        flash("Department updated successfully.", "success")
	                        
	                elif action == "toggle_department":
	                    dept_id = request.form.get("record_id")
	                    new_status = request.form.get("status")
	                    conn.execute("UPDATE departments SET status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE department_id = ?", (new_status, user_id, dept_id))
	                    flash(f"Department marked as {new_status}.", "success")

	                elif action == "add_location":
	                    name = request.form.get("location_name", "").strip()
	                    code = request.form.get("location_code", "").strip()
	                    city = request.form.get("city", "").strip()
	                    country = request.form.get("country", "").strip()
	                    address = request.form.get("address", "").strip()
	                    state = request.form.get("state", "").strip()
	                    postal_code = request.form.get("postal_code", "").strip()
	                    status = request.form.get("status", "Active")
	                    if not name or not code or not city or not country:
	                        flash("Location Name, Code, City, and Country are mandatory.", "error")
	                    else:
	                        conn.execute("INSERT INTO locations (location_name, location_code, city, country, address, state, postal_code, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, code, city, country, address, state, postal_code, status, user_id))
	                        flash("Location created successfully.", "success")
	                        
	                elif action == "edit_location":
	                    loc_id = request.form.get("record_id")
	                    name = request.form.get("location_name", "").strip()
	                    code = request.form.get("location_code", "").strip()
	                    city = request.form.get("city", "").strip()
	                    country = request.form.get("country", "").strip()
	                    address = request.form.get("address", "").strip()
	                    state = request.form.get("state", "").strip()
	                    postal_code = request.form.get("postal_code", "").strip()
	                    status = request.form.get("status", "Active")
	                    if not name or not code or not city or not country:
	                        flash("Location Name, Code, City, and Country are mandatory.", "error")
	                    else:
	                        conn.execute("UPDATE locations SET location_name = ?, location_code = ?, city = ?, country = ?, address = ?, state = ?, postal_code = ?, status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE location_id = ?", (name, code, city, country, address, state, postal_code, status, user_id, loc_id))
	                        flash("Location updated successfully.", "success")
	                        
	                elif action == "toggle_location":
	                    loc_id = request.form.get("record_id")
	                    new_status = request.form.get("status")
	                    conn.execute("UPDATE locations SET status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE location_id = ?", (new_status, user_id, loc_id))
	                    flash(f"Location marked as {new_status}.", "success")
	                elif action == "add_interest":
	                    name = request.form.get("interest_name", "").strip()
	                    if name:
	                        normalized = " ".join(name.lower().split())
	                        try:
	                            conn.execute("INSERT INTO interest_master (interest_name, normalized_name, created_by) VALUES (?, ?, ?)", (name, normalized, user_id))
	                            flash("Interest added successfully.", "success")
	                        except sqlite3.IntegrityError:
	                            flash("Interest already exists.", "error")
	                    else:
	                        flash("Interest name is required.", "error")
	                elif action == "edit_interest":
	                    i_id = request.form.get("interest_id")
	                    name = request.form.get("interest_name", "").strip()
	                    if name and i_id:
	                        normalized = " ".join(name.lower().split())
	                        try:
	                            conn.execute("UPDATE interest_master SET interest_name = ?, normalized_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, normalized, i_id))
	                            flash("Interest updated successfully.", "success")
	                        except sqlite3.IntegrityError:
	                            flash("An interest with that name already exists.", "error")
	                    else:
	                        flash("Interest name is required.", "error")
	                elif action == "toggle_interest_status":
	                    i_id = request.form.get("interest_id")
	                    new_status = request.form.get("status", "Active")
	                    conn.execute("UPDATE interest_master SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, i_id))
	                    flash(f"Interest marked as {new_status}.", "success")
	                    
	            except sqlite3.IntegrityError:
	                flash("Error: Name or Code must be unique.", "error")
	                
	        return redirect(safe_referrer(url_for('master_management')))
	        
	    with get_db() as connection:
	        departments = connection.execute("SELECT * FROM departments ORDER BY department_name").fetchall()
	        locations = connection.execute("SELECT * FROM locations ORDER BY location_name").fetchall()
	        
	    return render_template("master_management.html", departments=[dict(d) for d in departments], locations=[dict(l) for l in locations], user=session.get("user"), role=session.get("role"), profile_picture=session.get("profile_picture"))

	# Master-data quick-add endpoints, used by the Admin page (session) and by API clients (headers).
	@app.post("/api/v1/departments")
	@staff_session_or_api_required
	def api_add_department():
	    data = request.get_json(silent=True) or {}
	    name = (data.get("name") or "").strip()
	    if not name:
	        return {"error": "Department name is required."}, 400
	    code = ''.join([w[0] for w in name.split()]).upper()
	    if len(code) < 2: code = name[:3].upper()
	    with get_db() as connection:
	        try:
	            dept_id = connection.execute(
	                "INSERT INTO departments (department_name, department_code, created_by) VALUES (?, ?, ?)",
	                (name, code, g.api_user["id"])
	            ).lastrowid
	            return {"message": "Department added.", "id": dept_id, "name": name}, 201
	        except sqlite3.IntegrityError:
	            return {"error": "Department already exists."}, 409

	@app.post("/api/v1/positions")
	@staff_session_or_api_required
	def api_add_position():
	    data = request.get_json(silent=True) or {}
	    name = (data.get("name") or "").strip()
	    if not name:
	        return {"error": "Position name is required."}, 400
	    with get_db() as connection:
	        try:
	            pos_id = connection.execute(
	                "INSERT INTO positions (name, created_by) VALUES (?, ?)",
	                (name, g.api_user["id"])
	            ).lastrowid
	            return {"message": "Position added.", "id": pos_id, "name": name}, 201
	        except sqlite3.IntegrityError:
	            return {"error": "Position already exists."}, 409


	@app.post("/api/v1/locations")
	@staff_session_or_api_required
	def api_add_location():
	    data = request.get_json(silent=True) or {}
	    name = (data.get("name") or "").strip()
	    if not name:
	        return {"error": "Location name is required."}, 400
	    code = ''.join([w[0] for w in name.split()]).upper()
	    if len(code) < 3: code = name[:3].upper()
	    with get_db() as connection:
	        try:
	            loc_id = connection.execute(
	                "INSERT INTO locations (location_name, location_code, city, country, created_by) VALUES (?, ?, ?, ?, ?)",
	                (name, code, name, 'India', g.api_user["id"])
	            ).lastrowid
	            return {"message": "Location added.", "id": loc_id, "name": name}, 201
	        except sqlite3.IntegrityError:
	            return {"error": "Location already exists."}, 409

	@app.cli.command("init-db")
	def init_db_command():
		"""Create tables, apply init_scripts/*.sql and seed demo data (safe to re-run)."""
		init_db()
		with get_db() as connection:
			applied = applied_scripts(connection)
		print(f"Database ready: {DATABASE}")
		for name, applied_at in applied:
			print(f"  init script {name} (applied {applied_at})")

	return app


app = create_app()




if __name__ == "__main__":
	_host = os.getenv("LMS_HOST", "127.0.0.1")
	_debug_default = "1" if _host in ("127.0.0.1", "localhost", "::1") else "0"
	app.run(
		host=_host,
		port=int(os.getenv("LMS_PORT") or os.getenv("PORT") or "5000"),
		debug=os.getenv("LMS_DEBUG", _debug_default) == "1",
	)
