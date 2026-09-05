with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_headers = """                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Name</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Username</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Course IDs</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Role</th>"""

new_headers = """                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Name</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Username</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Emp ID</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Email</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Course IDs</th>
                          <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Role</th>"""

old_rows = """                          <td class="p-3 font-semibold">{{ item.full_name }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.username }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.course_ids or '—' }}</td>
                          <td class="p-3">"""

new_rows = """                          <td class="p-3 font-semibold">{{ item.full_name }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.username }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.employee_id or '—' }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.email or '—' }}</td>
                          <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.course_ids or '—' }}</td>
                          <td class="p-3">"""

old_search = """                          data-search="{{ item.full_name|lower }} {{ item.username|lower }} {{ item.role|lower }} {{ item.course_ids or '' }}"""
new_search = """                          data-search="{{ item.full_name|lower }} {{ item.username|lower }} {{ item.employee_id|default('')|lower }} {{ item.email|default('')|lower }} {{ item.role|lower }} {{ item.course_ids or '' }}"""

if old_headers in content:
    content = content.replace(old_headers, new_headers)
if old_rows in content:
    content = content.replace(old_rows, new_rows)
# Note: old_search might have variable ending quote, we can replace that dynamically
import re
content = re.sub(r'data-search="\{\{ item\.full_name\|lower \}\} \{\{ item\.username\|lower \}\} \{\{ item\.role\|lower \}\} \{\{ item\.course_ids or \'\' \}\}"',
                 r'data-search="{{ item.full_name|lower }} {{ item.username|lower }} {{ item.employee_id|default(\'\')|lower }} {{ item.email|default(\'\')|lower }} {{ item.role|lower }} {{ item.course_ids or \'\' }}"',
                 content)


with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS: Updated admin.html with employee ID and email ID.")
