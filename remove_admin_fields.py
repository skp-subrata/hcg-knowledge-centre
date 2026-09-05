with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

import re

# Remove the HTML block
html_pattern = r'<div class="md:col-span-2">\s*<label class="form-label flex justify-between">Interests.*?<textarea name="about_me" id="edit_about_me" class="form-input h-24" placeholder="Short professional or personal introduction"></textarea>\s*</div>'

content = re.sub(html_pattern, '', content, flags=re.DOTALL)

# Remove JS assignments in openEditUserModal
js_pattern = r"document\.getElementById\('edit_about_me'\)\.value = user\.about_me \|\| '';\s*// Set multi-select for interests\s*let intSelect = document\.getElementById\('edit_interests'\);\s*let intIds = \(user\.interest_ids \|\| ''\)\.split\(','\);\s*for \(let i = 0; i < intSelect\.options\.length; i\+\+\) \{\s*intSelect\.options\[i\]\.selected = intIds\.includes\(intSelect\.options\[i\]\.value\);\s*\}"

content = re.sub(js_pattern, '', content, flags=re.DOTALL)


with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Removed Interests and About Me from admin.html Edit User Modal")
