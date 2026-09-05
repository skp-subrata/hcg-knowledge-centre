with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(r"{{ item.employee_id|default(\'\')|lower }}", r"{{ item.employee_id|default('')|lower }}")
content = content.replace(r"{{ item.email|default(\'\')|lower }}", r"{{ item.email|default('')|lower }}")
content = content.replace(r"{{ item.course_ids or \'\' }}", r"{{ item.course_ids or '' }}")
content = content.replace(r"{{ item.employee_id or \'-\' }}", r"{{ item.employee_id or '-' }}")
content = content.replace(r"{{ item.email or \'-\' }}", r"{{ item.email or '-' }}")

with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Removed literal backslashes")
