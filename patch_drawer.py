import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The exact snippet we want to append after
target = '''                            Manage Assessments
                        </a>
                    </li>'''

management_section = '''
                    {% if role == 'admin' %}
                    <li class="pt-6 pb-2">
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">Management</p>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>
                            View / Add / Edit Users
                        </a>
                    </li>
                    {% endif %}'''

if target in content:
    content = content.replace(target, target + management_section)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
