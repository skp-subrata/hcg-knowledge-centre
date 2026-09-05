with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

import re

old_search = r'data-search="\{\{ item\.full_name\|lower \}\} \{\{ item\.username\|lower \}\} \{\{ item\.role\|lower \}\} \{\{ item\.course_ids or \'\' \}\}"'
new_search = r'data-search="{{ item.full_name|lower }} {{ item.username|lower }} {{ item.employee_id|default(\'\')|lower }} {{ item.email|default(\'\')|lower }} {{ item.role|lower }} {{ item.course_ids or \'\' }}"'

content = re.sub(old_search, new_search, content)

# I can't write out the EM DASH literal easily without risking encoding issues in the terminal string,
# so I will regex match the course_ids td line exactly.

# Replace the rows
old_rows = r'(<td class="p-3 text-slate-500 dark:text-slate-400 text-sm">\{\{ item\.username \}\}<\/td>\s*)(<td class="p-3 text-slate-500 dark:text-slate-400 text-sm">\{\{ item\.course_ids or \'.*?\' \}\}<\/td>)'

new_rows = r'\g<1><td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.employee_id or \'-\' }}</td>\n                        <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.email or \'-\' }}</td>\n                        \g<2>'

content = re.sub(old_rows, new_rows, content)

with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated admin.html rows with Emp ID and Email")
