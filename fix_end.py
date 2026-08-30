import sys

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('\t\t@app.get("/switch-role")'):
        line = '\t@app.get("/switch-role")\n'
    if line.startswith('\t\t@app.route("/profile"'):
        line = '\t@app.route("/profile", methods=["GET", "POST"])\n'
    new_lines.append(line)

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
