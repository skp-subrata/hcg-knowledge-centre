with open('d:/apps/templates/master_management.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the template string in JS
content = content.replace("const rows = document.querySelectorAll(# tbody tr);", "const rows = document.querySelectorAll(# tbody tr);")

with open('d:/apps/templates/master_management.html', 'w', encoding='utf-8') as f:
    f.write(content)
