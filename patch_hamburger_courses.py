import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the two old 'Create Course' and 'Edit / Manage Courses' items with one 'Courses' link
old_section = '''                    {% if role in ('admin', 'moderator') %}
                    <li class="pt-6 pb-2">
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">Courses</p>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                            Create Course
                        </a>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                            Edit / Manage Courses
                        </a>
                    </li>'''

new_section = '''                    {% if role in ('admin', 'moderator') %}
                    <li class="pt-6 pb-2">
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">Learning & Development</p>
                    </li>
                    <li>
                        <a href="{{ url_for('courses_page') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"></path></svg>
                            Courses
                        </a>
                    </li>'''

if old_section in content:
    content = content.replace(old_section, new_section)
    print("Hamburger updated.")
else:
    print("Old section not found, trying partial match...")
    # fallback: just check if courses_page is already there
    if "courses_page" in content:
        print("Already updated.")
    else:
        print("WARNING: Could not find the section to replace.")

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
