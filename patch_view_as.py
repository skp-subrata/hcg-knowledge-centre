import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_route = '''	@app.get("/view-as")
	@admin_required
	def view_as_page():
		with get_db() as connection:
			students = connection.execute("SELECT id, full_name, username FROM users WHERE role = 'basic user' ORDER BY full_name").fetchall()
		return render_template("view_as.html", students=students, user=session.get("user"), role=session.get("role"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"))

'''

content = content.replace('@app.post("/admin/view-as/<int:user_id>")', new_route + '\t@app.post("/admin/view-as/<int:user_id>")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
