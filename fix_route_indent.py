with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("\n@app.route('/api/v1/releases/active', methods=['GET'])", "\n\t@app.route('/api/v1/releases/active', methods=['GET'])")

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Fixed @app.route indentation!")
