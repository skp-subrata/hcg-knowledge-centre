import sys
with open('templates/assessment.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '<button class="btn-primary text-lg px-8">Submit assessment</button>',
    '<button class="btn-primary flex items-center justify-center w-14 h-14 mx-auto rounded-full" title="Submit Assessment"><svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg></button>'
)

with open('templates/assessment.html', 'w', encoding='utf-8') as f:
    f.write(content)
