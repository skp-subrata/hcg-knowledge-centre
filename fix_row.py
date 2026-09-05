with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace users passing
old_ret = 'return render_template("admin.html", users=users, courses=courses'
new_ret = 'return render_template("admin.html", users=[dict(u) for u in users], courses=courses'
content = content.replace(old_ret, new_ret)

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
