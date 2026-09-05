import re

with open('d:/apps/templates/master_management.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Tab Button
tab_target = '''        <button id="tab-loc" class="px-6 py-3 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors" onclick="switchTab('loc')">Location</button>
    </div>'''
tab_replacement = '''        <button id="tab-loc" class="px-6 py-3 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors" onclick="switchTab('loc')">Location</button>
        <button id="tab-int" class="px-6 py-3 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 transition-colors" onclick="switchTab('int')">Interest</button>
    </div>'''
content = content.replace(tab_target, tab_replacement)

# 2. Add Tab Content Panel
panel_target = '''    <!-- Location Tab -->
    <div id="panel-loc" class="space-y-6 hidden">'''

interest_panel = '''    <!-- Interest Tab -->
    <div id="panel-int" class="space-y-6 hidden">
        <div class="glass-panel p-6">
            <div class="flex flex-col sm:flex-row justify-between items-center gap-4 mb-5">
                <div class="flex gap-4 w-full sm:w-auto">
                    <input type="text" id="int-search" class="form-input text-sm w-full sm:w-64" placeholder="Search Interest..." oninput="filterTable('int-table', 'int-search', 'int-status-filter')">
                    <select id="int-status-filter" class="form-input text-sm w-32" onchange="filterTable('int-table', 'int-search', 'int-status-filter')">
                        <option value="">All Status</option>
                        <option value="active">Active</option>
                        <option value="inactive">Inactive</option>
                    </select>
                </div>
                <button onclick="openIntModal(null)" class="btn-primary flex items-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                    Add New
                </button>
            </div>
            
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm" id="int-table">
                    <thead>
                        <tr class="border-b border-slate-200 dark:border-slate-800 text-slate-500">
                            <th class="p-3 font-bold uppercase">Interest Name</th>
                            <th class="p-3 font-bold uppercase">Normalized Name</th>
                            <th class="p-3 font-bold uppercase">Status</th>
                            <th class="p-3 font-bold uppercase">Created Date</th>
                            <th class="p-3 font-bold uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                        {% for i in interests %}
                        <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50" data-search="{{ i.interest_name|lower }} {{ i.normalized_name|lower }}" data-status="{{ i.status|lower }}">
                            <td class="p-3 font-semibold">{{ i.interest_name }}</td>
                            <td class="p-3 text-slate-500">{{ i.normalized_name }}</td>
                            <td class="p-3">
                                <span class="px-2 py-0.5 rounded-full text-xs font-semibold {% if i.status == 'Active' %}bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400{% else %}bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400{% endif %}">{{ i.status }}</span>
                            </td>
                            <td class="p-3">{{ i.created_at }}</td>
                            <td class="p-3">
                                <div class="flex items-center gap-3">
                                    <button onclick='openIntModal({{ i|tojson }})' class="text-indigo-600 dark:text-indigo-400 hover:underline font-medium">Edit</button>
                                    <span class="text-slate-300 dark:text-slate-700">|</span>
                                    <form method="post" class="inline" onsubmit="return confirm('{% if i.status == 'Active' %}Are you sure you want to deactivate this master?{% else %}Reactivate this master?{% endif %}');">
                                        <input type="hidden" name="action" value="toggle_interest_status">
                                        <input type="hidden" name="interest_id" value="{{ i.id }}">
                                        <button type="submit" class="font-medium {% if i.status == 'Active' %}text-red-500 hover:text-red-700 dark:hover:text-red-400{% else %}text-green-600 hover:text-green-700 dark:text-green-500 dark:hover:text-green-400{% endif %}">
                                            {% if i.status == 'Active' %}Deactivate{% else %}Activate{% endif %}
                                        </button>
                                    </form>
                                </div>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" class="p-4 text-center text-slate-500">No interests found.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
''' + panel_target
content = content.replace(panel_target, interest_panel)

# 3. Add Interest Modal
modal_target = '''<!-- Location Modal -->'''
interest_modal = '''<!-- Interest Modal -->
<div id="intModal" class="fixed inset-0 z-[100] hidden flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
    <div class="bg-white dark:bg-slate-900 rounded-2xl w-full max-w-lg shadow-2xl relative">
        <button onclick="document.getElementById('intModal').classList.add('hidden')" type="button" class="absolute top-4 right-4 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
        <div class="p-6">
            <h2 id="intModalTitle" class="text-xl font-bold text-slate-900 dark:text-white mb-6">Create Interest</h2>
            <form method="post" class="space-y-4">
                <input type="hidden" name="action" id="intAction" value="add_interest">
                <input type="hidden" name="interest_id" id="intId">
                
                <div>
                    <label class="form-label">Interest Name *</label>
                    <input type="text" name="interest_name" id="intName" class="form-input" required placeholder="e.g. Photography">
                </div>
                <div class="pt-4 flex gap-3">
                    <button type="button" onclick="document.getElementById('intModal').classList.add('hidden')" class="btn-secondary flex-1">Cancel</button>
                    <button type="submit" class="btn-primary flex-1" id="intSubmitBtn">Create Interest</button>
                </div>
            </form>
        </div>
    </div>
</div>

''' + modal_target
content = content.replace(modal_target, interest_modal)

# 4. Add openIntModal JS
js_target = '''function switchTab(tab) {'''
int_js = '''
function openIntModal(intObj) {
    if(intObj) {
        document.getElementById('intModalTitle').textContent = "Edit Interest";
        document.getElementById('intSubmitBtn').textContent = "Update Interest";
        document.getElementById('intAction').value = "edit_interest";
        document.getElementById('intId').value = intObj.id || '';
        document.getElementById('intName').value = intObj.interest_name || '';
    } else {
        document.getElementById('intModalTitle').textContent = "Create Interest";
        document.getElementById('intSubmitBtn').textContent = "Create Interest";
        document.getElementById('intAction').value = "add_interest";
        document.getElementById('intId').value = "";
        document.getElementById('intName').value = "";
    }
    document.getElementById('intModal').classList.remove('hidden');
}

''' + js_target
content = content.replace(js_target, int_js)

# 5. Update switchTab logic
switch_tab_target = '''    document.getElementById('panel-dept').classList.add('hidden');
    document.getElementById('panel-loc').classList.add('hidden');
    document.getElementById('tab-dept').classList.replace('border-indigo-600', 'border-transparent');
    document.getElementById('tab-dept').classList.replace('text-indigo-600', 'text-slate-500');
    document.getElementById('tab-loc').classList.replace('border-indigo-600', 'border-transparent');
    document.getElementById('tab-loc').classList.replace('text-indigo-600', 'text-slate-500');'''

switch_tab_replacement = '''    document.getElementById('panel-dept').classList.add('hidden');
    document.getElementById('panel-loc').classList.add('hidden');
    document.getElementById('panel-int').classList.add('hidden');
    
    const tabs = ['dept', 'loc', 'int'];
    tabs.forEach(t => {
        document.getElementById('tab-' + t).classList.replace('border-indigo-600', 'border-transparent');
        document.getElementById('tab-' + t).classList.replace('text-indigo-600', 'text-slate-500');
        document.getElementById('tab-' + t).classList.remove('dark:text-indigo-400');
    });'''

content = content.replace(switch_tab_target, switch_tab_replacement)

with open('d:/apps/templates/master_management.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated master_management.html for interest master.")
