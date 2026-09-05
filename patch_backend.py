import re

with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update /profile route to remove old user_interests logic
profile_target = '''				connection.execute("DELETE FROM user_interests WHERE user_id = ?", (session["user_id"],))
				for int_id in interests:
					if int_id:
						connection.execute("INSERT INTO user_interests (user_id, interest_id) VALUES (?, ?)", (session["user_id"], int_id))
'''
content = content.replace(profile_target, '')

# 2. Update /api/v1/interests and add the new ones
# We'll just define them inside create_app

new_api = '''
	@app.get("/api/interests")
	def get_interests():
		search = request.args.get("search", "").strip()
		with get_db() as conn:
			if search:
				query = "SELECT id, interest_name as name FROM interest_master WHERE status = 'Active' AND interest_name LIKE ? ORDER BY interest_name"
				rows = conn.execute(query, (f"%{search}%",)).fetchall()
			else:
				rows = conn.execute("SELECT id, interest_name as name FROM interest_master WHERE status = 'Active' ORDER BY interest_name").fetchall()
		return jsonify([dict(r) for r in rows])

	@app.post("/api/interests")
	def create_interest():
		data = request.get_json(silent=True) or {}
		name = (data.get("interest_name") or "").strip()
		if not name:
			return {"error": "Interest name is required."}, 400
		
		normalized = " ".join(name.lower().split())
		user_id = session.get("user_id") or getattr(g, "api_user", {}).get("id")
		
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
'''

# Find a good place to insert this inside create_app
insert_target = '\t@app.get("/api/v1/docs")'
if insert_target in content:
    content = content.replace(insert_target, new_api + '\n' + insert_target)
else:
    print("Could not find insert target")

# Remove the old api_add_interest
old_api_target = r'@app\.post\("/api/v1/interests"\)\n@api_required\ndef api_add_interest\(\):.*?(?=\n@app\.)'
content = re.sub(old_api_target, '', content, flags=re.DOTALL)

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Backend API patched successfully.")
