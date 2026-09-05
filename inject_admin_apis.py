with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

endpoints_code = """
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

		data_sql = f\"\"\"
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
		\"\"\"
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

		data_sql = f\"\"\"
			SELECT c.*, u.full_name AS creator 
			FROM courses c 
			LEFT JOIN users u ON u.id = c.created_by 
			{where_str}
			ORDER BY c.id DESC
			LIMIT ? OFFSET ?
		\"\"\"
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

		data_sql = f\"\"\"
			SELECT ac.*, u.username, u.full_name, u.role 
			FROM api_credentials ac 
			JOIN users u ON u.id = ac.user_id 
			{where_str}
			ORDER BY ac.id DESC
			LIMIT ? OFFSET ?
		\"\"\"
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

		data_sql = f\"\"\"
			SELECT a.id, a.title, a.type, a.course_id, c.name AS course_name 
			FROM assessments a 
			LEFT JOIN courses c ON c.id = a.course_id 
			{where_str}
			ORDER BY a.id DESC
			LIMIT ? OFFSET ?
		\"\"\"
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

"""

if "/api/admin/users" not in content:
    content = content.replace("@app.route('/api/v1/releases/active'", endpoints_code + "\n@app.route('/api/v1/releases/active'")

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Injected server-side admin pagination & search API endpoints into app.py!")
