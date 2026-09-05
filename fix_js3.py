import re
with open('d:/apps/templates/master_management.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'querySelectorAll\(# tbody tr\)', r'querySelectorAll(# tbody tr)', content)

with open('d:/apps/templates/master_management.html', 'w', encoding='utf-8') as f:
    f.write(content)
