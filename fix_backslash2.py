with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(r"{{ item.course_ids or \'\' }}", r"{{ item.course_ids or '' }}")

with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Removed literal backslash from course_ids")
