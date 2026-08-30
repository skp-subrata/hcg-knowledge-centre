import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

edit_profile_link = '''                          <a href="{{ url_for('profile') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                              <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                              Edit Profile
                          </a>'''

view_as_link = '''
                          {% if actual_role in ('admin', 'moderator') and not impersonating %}
                          <a href="{{ url_for('view_as_page') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                              <svg class="w-4 h-4 text-sky-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                              View As...
                          </a>
                          {% endif %}'''

if edit_profile_link in content:
    content = content.replace(edit_profile_link, edit_profile_link + view_as_link)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
