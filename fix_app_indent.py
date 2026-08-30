import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the indentations
content = content.replace('\t\t@app.get("/switch-role")', '\t@app.get("/switch-role")')
# Wait, let's just make sure all of switch_role and profile are indented with one tab
# In my string I used:
'''	@app.get("/switch-role")
	def switch_role():'''

# Let's see what the context is
