with open('d:/apps/templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

target = 'View / Add / Edit Users\n                        </a>\n                    </li>'
new_item = '''
                    <li>
                        <a href="{{ url_for('master_management') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg>
                            Master Management
                        </a>
                    </li>
'''
content = content.replace(target, target + new_item)

with open('d:/apps/templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
