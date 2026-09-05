import re

with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Let's insert the interest logic right after toggle_location
target = '''	                elif action == "toggle_location":
	                    loc_id = request.form.get("record_id")
	                    new_status = request.form.get("status")
	                    conn.execute("UPDATE locations SET status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE location_id = ?", (new_status, user_id, loc_id))
	                    flash(f"Location marked as {new_status}.")'''

replacement = target + '''
	                elif action == "add_interest":
	                    name = request.form.get("interest_name", "").strip()
	                    if name:
	                        normalized = " ".join(name.lower().split())
	                        try:
	                            conn.execute("INSERT INTO interest_master (interest_name, normalized_name, created_by) VALUES (?, ?, ?)", (name, normalized, user_id))
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
	                            conn.execute("UPDATE interest_master SET interest_name = ?, normalized_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, normalized, i_id))
	                            flash("Interest updated successfully.")
	                        except sqlite3.IntegrityError:
	                            flash("An interest with that name already exists.")
	                    else:
	                        flash("Interest name is required.")
	                elif action == "toggle_interest_status":
	                    i_id = request.form.get("interest_id")
	                    new_status = request.form.get("status", "Active")
	                    conn.execute("UPDATE interest_master SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, i_id))
	                    flash(f"Interest marked as {new_status}.")'''

if target in content:
    content = content.replace(target, replacement)
    with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Patch applied successfully.")
else:
    print("Could not find target block.")
