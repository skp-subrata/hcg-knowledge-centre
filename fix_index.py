import sys

with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace "Enter classroom" with a beautiful Icon
content = content.replace(
    '<button class="btn-primary w-full">Enter classroom</button>',
    '<button class="btn-primary w-full flex justify-center py-3.5" title="Sign In"><svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" /></svg></button>'
)

# Replace "Open &rarr;" with just a crisp icon button
content = content.replace(
    '''<a class="text-slate-900 dark:text-slate-100 font-medium text-sm hover:underline" href="{{ url_for('course_detail', course_id=course.id) }}">
                Open &rarr;
            </a>''',
    '''<a class="w-8 h-8 flex items-center justify-center rounded-full bg-slate-900/10 dark:bg-slate-100/10 hover:bg-slate-900/20 dark:hover:bg-slate-100/20 text-slate-900 dark:text-slate-100 transition-colors" href="{{ url_for('course_detail', course_id=course.id) }}" title="Open Course">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" /></svg>
            </a>'''
)

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
