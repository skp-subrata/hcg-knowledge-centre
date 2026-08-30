import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update init_db for migration
migration_code = '''
		# Migrate users table for profile fields
		table_info = connection.execute("PRAGMA table_info(users)").fetchall()
		columns = [col['name'] for col in table_info]
		if 'email' not in columns:
			connection.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN phone_number TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT DEFAULT ''")
'''

content = content.replace(
    'connection.execute("PRAGMA foreign_keys = OFF")',
    migration_code + '\n\t\t\t\tconnection.execute("PRAGMA foreign_keys = OFF")'
)

# 2. Update login logic
old_login = '''			if user and check_password_hash(user["password_hash"], password):
				session.pop("impersonator_id", None)
				session.update(user=user["full_name"], user_id=user["id"], role=user["role"])
				return redirect(url_for("home"))'''

new_login = '''			if user and check_password_hash(user["password_hash"], password):
				session.pop("impersonator_id", None)
				session.update(
                    user=user["full_name"], 
                    user_id=user["id"], 
                    actual_role=user["role"], 
                    role="basic user", # Always login as basic user
                    profile_picture=user.get("profile_picture", "")
                )
				return redirect(url_for("home"))'''

content = content.replace(old_login, new_login)


# 3. Add switch_role and profile endpoints
new_endpoints = '''	@app.get("/switch-role")
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

'''

content = content.replace('@app.get("/logout")', new_endpoints + '\n\t@app.get("/logout")')

# Make sure template variables include actual_role and profile_picture
content = content.replace(
    'user=session["user"], role=session["role"]',
    'user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture")'
)
content = content.replace(
    'user=session.get("user"), role=session.get("role")',
    'user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture")'
)
# Ensure we catch variations
content = content.replace(
    'role=session["role"]',
    'role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture")'
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
