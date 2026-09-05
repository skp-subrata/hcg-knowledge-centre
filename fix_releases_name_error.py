with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add releases = connection.execute(...) in admin_panel
old_admin_fetch = """			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE status = 'Active' ORDER BY location_name").fetchall()
			courses = connection.execute"""

new_admin_fetch = """			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE status = 'Active' ORDER BY location_name").fetchall()
			releases = connection.execute("SELECT * FROM app_releases ORDER BY id DESC").fetchall()
			courses = connection.execute"""

content = content.replace(old_admin_fetch, new_admin_fetch, 1)

# 2. Add releases = connection.execute(...) in profile
old_profile_fetch = """			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE status = 'Active' ORDER BY location_name").fetchall()
		return render_template("profile.html\""""

new_profile_fetch = """			master_locations = connection.execute("SELECT location_id as id, location_name as name FROM locations WHERE status = 'Active' ORDER BY location_name").fetchall()
			releases = connection.execute("SELECT * FROM app_releases ORDER BY id DESC").fetchall()
		return render_template("profile.html\""""

content = content.replace(old_profile_fetch, new_profile_fetch, 1)

# 3. Add releases to context processor globally as fallback
old_cp = """	@app.context_processor
	def inject_notifications():
		if session.get("user_id"):
			try:
				with get_db() as connection:
					count = connection.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (session["user_id"],)).fetchone()["n"]
					return {"unread_notifications_count": count}
			except Exception:
											pass
		return {"unread_notifications_count": 0}"""

new_cp = """	@app.context_processor
	def inject_notifications():
		unread = 0
		releases = []
		if session.get("user_id"):
			try:
				with get_db() as connection:
					count = connection.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (session["user_id"],)).fetchone()["n"]
					unread = count
			except Exception:
				pass
		try:
			with get_db() as connection:
				releases = connection.execute("SELECT * FROM app_releases ORDER BY id DESC").fetchall()
		except Exception:
			pass
		return {"unread_notifications_count": unread, "releases": releases}"""

content = content.replace(old_cp, new_cp)

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: releases variable defined in routes and context processor")
