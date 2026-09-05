with open('d:/apps/templates/master_management.html', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''<input type="hidden" name="action" value="toggle_interest_status">
                                        <input type="hidden" name="interest_id" value="{{ i.id }}">'''
replacement = target + '''\n                                        <input type="hidden" name="status" value="{% if i.status == 'Active' %}Inactive{% else %}Active{% endif %}">'''

content = content.replace(target, replacement)
with open('d:/apps/templates/master_management.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("HTML patched.")
