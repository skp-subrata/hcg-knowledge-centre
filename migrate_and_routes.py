import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# --- 1. DB MIGRATION ---------------------------------------------------------
# Add after the existing profile migration block
migration_courses = '''
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
'''

if "# Migrate courses table" not in content:
    content = content.replace(
        "connection.execute(\"INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)\",",
        migration_courses + '\n\t\tconnection.execute("INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)",'
    )

# --- 2. NEW ROUTES -----------------------------------------------------------
new_routes = '''
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

'''

if '"def courses_page():' not in content and 'def courses_page' not in content:
    content = content.replace('\t@app.get("/view-as")', new_routes + '\n\t@app.get("/view-as")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done patching app.py")
