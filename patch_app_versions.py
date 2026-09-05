import re

with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Database table
table_sql = """			CREATE TABLE IF NOT EXISTS app_releases (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				version_number TEXT UNIQUE NOT NULL,
				release_title TEXT NOT NULL,
				release_date TEXT DEFAULT CURRENT_TIMESTAMP,
				features TEXT,
				improvements TEXT,
				bug_fixes TEXT,
				is_active INTEGER DEFAULT 0
			);"""

if "CREATE TABLE IF NOT EXISTS app_releases" not in content:
    # Insert after api_credentials
    content = content.replace("CREATE TABLE IF NOT EXISTS api_credentials (", table_sql + "\n\n			CREATE TABLE IF NOT EXISTS api_credentials (")

# 2. Database seed
seed_sql = """			# Seed initial release if empty
			release_count = connection.execute("SELECT COUNT(*) FROM app_releases").fetchone()[0]
			if release_count == 0:
				connection.execute('''
					INSERT INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active)
					VALUES (?, ?, ?, ?, ?, 1)
				''', (
					'1.5.0', 
					'1.5.0 Release', 
					'["Interactive Profile Customization with Interest Chips", "Dynamic Release Notes Engine"]',
					'["Streamlined Add User Admin Workflow", "Restored Edit User Popup Wizard"]',
					'["Fixed template syntax error on Admin panel"]'
				))
"""
if "Seed initial release if empty" not in content:
    content = content.replace("print(\"Database initialized successfully.\")", seed_sql + "\n			print(\"Database initialized successfully.\")")

# 3. API Endpoint
api_endpoint = """
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
"""
if "def get_active_release():" not in content:
    content = content.replace("@app.route('/api/v1/users', methods=['GET'])", api_endpoint + "\n@app.route('/api/v1/users', methods=['GET'])")


# 4. Admin Panel POST actions
admin_actions = """			elif action == "create_release" and session.get("role") == "admin":
				version_number = request.form.get("version_number", "").strip()
				release_title = request.form.get("release_title", "").strip()
				features = request.form.get("features", "[]").strip()
				improvements = request.form.get("improvements", "[]").strip()
				bug_fixes = request.form.get("bug_fixes", "[]").strip()
				try:
					with get_db() as connection:
						connection.execute('''INSERT INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active) VALUES (?, ?, ?, ?, ?, 0)''', (version_number, release_title, features, improvements, bug_fixes))
					flash(f"Release {version_number} created.", "success")
				except Exception as e:
					flash(f"Error creating release: {str(e)}", "error")
				return redirect(url_for('admin_panel') + '#releases-section')
			elif action == "update_release" and session.get("role") == "admin":
				record_id = request.form.get("record_id")
				release_title = request.form.get("release_title", "").strip()
				features = request.form.get("features", "[]").strip()
				improvements = request.form.get("improvements", "[]").strip()
				bug_fixes = request.form.get("bug_fixes", "[]").strip()
				with get_db() as connection:
					connection.execute('''UPDATE app_releases SET release_title=?, features=?, improvements=?, bug_fixes=? WHERE id=?''', (release_title, features, improvements, bug_fixes, record_id))
				flash("Release updated.", "success")
				return redirect(url_for('admin_panel') + '#releases-section')
			elif action == "set_active_release" and session.get("role") == "admin":
				record_id = request.form.get("record_id")
				with get_db() as connection:
					connection.execute('UPDATE app_releases SET is_active = 0')
					connection.execute('UPDATE app_releases SET is_active = 1 WHERE id=?', (record_id,))
				flash("Active release updated.", "success")
				return redirect(url_for('admin_panel') + '#releases-section')
"""
if "elif action == \"create_release\"" not in content:
    content = content.replace("return redirect(url_for('admin_panel'))", "return redirect(url_for('admin_panel'))\n" + admin_actions, 1)

# 5. Pass releases to admin.html
admin_context = """			releases = connection.execute("SELECT * FROM app_releases ORDER BY id DESC").fetchall()
			master_locations = connection.execute("SELECT id, name FROM locations WHERE status = 'active' ORDER BY name").fetchall()"""
if "SELECT * FROM app_releases" not in content:
    content = content.replace("master_locations = connection.execute(\"SELECT id, name FROM locations WHERE status = 'active' ORDER BY name\").fetchall()", admin_context)

if "master_locations=master_locations" in content and "releases=releases" not in content:
    content = content.replace("master_locations=master_locations", "master_locations=master_locations, releases=releases")

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS: Updated app.py with version backend")
