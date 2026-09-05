import re

with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the injected route at the bottom
pattern = r'@app\.route\("/admin/masters".*?(?=\nif __name__ == "__main__":)'
match = re.search(pattern, content, flags=re.DOTALL)

if match:
    route_code = match.group(0)
    # Remove from bottom
    content = content.replace(route_code, '')
    
    # We need to indent it by 1 tab (or 4 spaces) to put it inside create_app()
    # The codebase seems to use tabs. Let's use 1 tab for each line.
    indented_route = '\n'.join(['\t' + line if line else line for line in route_code.split('\n')])
    
    # Insert it before the return app in create_app()
    insert_target = '\treturn app\n'
    content = content.replace(insert_target, indented_route + '\n\treturn app\n')
    
    with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Moved route inside create_app()')
else:
    print('Route not found at the bottom.')
