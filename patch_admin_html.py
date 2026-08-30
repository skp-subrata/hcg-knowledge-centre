import sys

with open('templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

target = '<h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50 mb-5">Users</h2>'
new_target = '<h2 id="users" class="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50 mb-5 pt-8 -mt-8">Users</h2>'

if target in content:
    content = content.replace(target, new_target)

with open('templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
