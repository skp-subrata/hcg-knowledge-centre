import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\t\t@app.get("/view-as")', '\t@app.get("/view-as")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
