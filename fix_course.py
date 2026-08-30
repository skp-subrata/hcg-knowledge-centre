import sys

with open('templates/course.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace "Mark as completed" text with just the icon and a title
content = content.replace(
    '''<button class="btn-primary flex items-center gap-2">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                        Mark as completed
                    </button>''',
    '''<button class="btn-primary flex items-center justify-center w-12 h-12" title="Mark as completed">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg>
                    </button>'''
)

# Open external resource
content = content.replace(
    '''<a href="{{ course.content_url }}" target="_blank" rel="noopener" class="btn-secondary inline-block">
                        Open external resource <span aria-hidden="true">&nearr;</span>
                    </a>''',
    '''<a href="{{ course.content_url }}" target="_blank" rel="noopener" class="btn-secondary flex items-center justify-center w-12 h-12 mx-auto" title="Open external resource">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                    </a>'''
)

with open('templates/course.html', 'w', encoding='utf-8') as f:
    f.write(content)
