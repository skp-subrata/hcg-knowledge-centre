import re

with open('d:/apps/templates/master_management.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Tab Button
content = re.sub(r'\s*<button id="tab-int".*?>Interest</button>', '', content)

# 2. Remove Tab Content Panel
panel_pattern = r'<!-- Interest Tab -->\s*<div id="panel-int" class="space-y-6 hidden">.*?</div>\s*</div>\s*</div>'
content = re.sub(panel_pattern, '', content, flags=re.DOTALL)

# 3. Remove Interest Modal
modal_pattern = r'<!-- Interest Modal -->\s*<div id="intModal" class="fixed inset-0 z-\[100\].*?</div>\s*</div>\s*</div>'
content = re.sub(modal_pattern, '', content, flags=re.DOTALL)

# 4. Remove openIntModal JS
js_pattern = r'function openIntModal\(intObj\) \{.*?\n\}\n'
content = re.sub(js_pattern, '', content, flags=re.DOTALL)

# 5. Revert switchTab logic
switch_tab_old = '''    document.getElementById('panel-dept').classList.add('hidden');
    document.getElementById('panel-loc').classList.add('hidden');
    document.getElementById('panel-int').classList.add('hidden');
    
    const tabs = ['dept', 'loc', 'int'];
    tabs.forEach(t => {
        document.getElementById('tab-' + t).classList.replace('border-indigo-600', 'border-transparent');
        document.getElementById('tab-' + t).classList.replace('text-indigo-600', 'text-slate-500');
        document.getElementById('tab-' + t).classList.remove('dark:text-indigo-400');
    });'''

switch_tab_new = '''    document.getElementById('panel-dept').classList.add('hidden');
    document.getElementById('panel-loc').classList.add('hidden');
    document.getElementById('tab-dept').classList.replace('border-indigo-600', 'border-transparent');
    document.getElementById('tab-dept').classList.replace('text-indigo-600', 'text-slate-500');
    document.getElementById('tab-loc').classList.replace('border-indigo-600', 'border-transparent');
    document.getElementById('tab-loc').classList.replace('text-indigo-600', 'text-slate-500');'''

content = content.replace(switch_tab_old, switch_tab_new)

with open('d:/apps/templates/master_management.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Removed Interest UI from master_management.html")
