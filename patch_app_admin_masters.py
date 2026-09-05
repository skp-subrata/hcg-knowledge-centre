import re

with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update GET to fetch interests
get_target = '''			locations = connection.execute("SELECT * FROM locations ORDER BY location_name").fetchall()
		return render_template("master_management.html", departments=departments, locations=locations)'''

get_replacement = '''			locations = connection.execute("SELECT * FROM locations ORDER BY location_name").fetchall()
			interests = connection.execute("SELECT * FROM interest_master ORDER BY interest_name").fetchall()
		return render_template("master_management.html", departments=departments, locations=locations, interests=interests)'''

content = content.replace(get_target, get_replacement)


# 2. Update POST to handle the new actions
post_target = '''			elif action == "toggle_location_status":
				loc_id = request.form.get("location_id")
				current_status = connection.execute("SELECT status FROM locations WHERE location_id = ?", (loc_id,)).fetchone()["status"]
				new_status = 'Inactive' if current_status == 'Active' else 'Active'
				connection.execute("UPDATE locations SET status = ? WHERE location_id = ?", (new_status, loc_id))
				flash(f"Location status changed to {new_status}.")'''

post_replacement = post_target + '''
			elif action == "add_interest":
				name = request.form.get("interest_name", "").strip()
				if name:
					normalized = " ".join(name.lower().split())
					try:
						connection.execute("INSERT INTO interest_master (interest_name, normalized_name, created_by) VALUES (?, ?, ?)", (name, normalized, session["user_id"]))
						flash("Interest added successfully.")
					except sqlite3.IntegrityError:
						flash("Interest already exists.")
				else:
					flash("Interest name is required.")
			elif action == "edit_interest":
				i_id = request.form.get("interest_id")
				name = request.form.get("interest_name", "").strip()
				if name and i_id:
					normalized = " ".join(name.lower().split())
					try:
						connection.execute("UPDATE interest_master SET interest_name = ?, normalized_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, normalized, i_id))
						flash("Interest updated successfully.")
					except sqlite3.IntegrityError:
						flash("An interest with that name already exists.")
				else:
					flash("Interest name is required.")
			elif action == "toggle_interest_status":
				i_id = request.form.get("interest_id")
				current_status = connection.execute("SELECT status FROM interest_master WHERE id = ?", (i_id,)).fetchone()["status"]
				new_status = 'Inactive' if current_status == 'Active' else 'Active'
				connection.execute("UPDATE interest_master SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, i_id))
				flash(f"Interest status changed to {new_status}.")'''

content = content.replace(post_target, post_replacement)

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated app.py backend logic for master management.")
