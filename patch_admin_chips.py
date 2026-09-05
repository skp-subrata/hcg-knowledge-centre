import re

with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the interests select in admin edit modal
old_admin_select = '''<div class="md:col-span-2">
                        <label class="form-label flex justify-between">Interests <a href="#" onclick="addMaster('interests', this)" class="text-indigo-500 hover:underline text-[10px]">[+ Add Interest]</a></label>
                        <select name="interests" id="edit_interests" multiple class="form-input h-24 int-select">
                            {% for i in master_interests %}
                            <option value="{{ i.id }}">{{ i.name }}</option>
                            {% endfor %}
                        </select>
                    </div>'''

new_admin_select = '''<div class="md:col-span-2 relative" id="admin-interest-container">
                        <label class="form-label">Interests</label>
                        <div class="form-input flex flex-wrap gap-2 items-center min-h-[42px] p-2" id="admin-interest-chips" style="height: auto;">
                            <div class="flex-1 min-w-[200px] relative">
                                <input type="text" id="admin-interest-input" class="w-full bg-transparent border-none focus:ring-0 text-sm p-0 m-0 outline-none dark:text-white" placeholder="Type to search or add an interest..." autocomplete="off">
                                <div id="admin-interest-dropdown" class="absolute left-0 right-0 top-full mt-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl z-50 hidden max-h-60 overflow-y-auto">
                                </div>
                            </div>
                        </div>
                    </div>'''
                    
content = content.replace(old_admin_select, new_admin_select)

# We also need to update the openEditUserModal to initialize the chips
init_chips = '''
    // Initialize interactive interests
    adminTargetUserId = user.id;
    loadAdminInterests();
    
    document.getElementById('editUserModal').classList.remove('hidden');
'''

content = content.replace("document.getElementById('editUserModal').classList.remove('hidden');", init_chips)

# Now we add the Javascript to handle the admin interactive chips
admin_chip_js = '''
let adminTargetUserId = null;
let adminActiveInterests = [];
const adminInput = document.getElementById('admin-interest-input');
const adminDropdown = document.getElementById('admin-interest-dropdown');
const adminChipsContainer = document.getElementById('admin-interest-chips');

async function loadAdminInterests() {
    if (!adminTargetUserId) return;
    const res = await fetch(/api/users//interests);
    adminActiveInterests = await res.json();
    renderAdminChips();
}

function renderAdminChips() {
    document.querySelectorAll('.admin-interest-chip').forEach(e => e.remove());
    const inputWrapper = adminInput.parentElement;
    adminActiveInterests.forEach(i => {
        const chip = document.createElement('span');
        chip.className = "admin-interest-chip inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-300";
        chip.innerHTML = ${i.name} <button type="button" class="hover:text-indigo-900 dark:hover:text-indigo-100 ml-1" onclick="removeAdminInterest()">&times;</button>;
        adminChipsContainer.insertBefore(chip, inputWrapper);
    });
}

async function removeAdminInterest(interestId) {
    if (!adminTargetUserId) return;
    await fetch(/api/users//interests/, { method: 'DELETE' });
    adminActiveInterests = adminActiveInterests.filter(i => i.id !== interestId);
    renderAdminChips();
}

async function addAdminInterest(interestId, interestName) {
    adminDropdown.classList.add('hidden');
    adminInput.value = '';
    if (!adminTargetUserId) return;
    
    if (adminActiveInterests.find(i => i.id === interestId)) return;
    
    await fetch(/api/users//interests, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_id: interestId})
    });
    
    adminActiveInterests.push({id: interestId, name: interestName});
    renderAdminChips();
}

async function createAdminNewInterest(name) {
    adminDropdown.classList.add('hidden');
    adminInput.value = '';
    
    const res = await fetch('/api/interests', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_name: name})
    });
    const newInt = await res.json();
    if(newInt.id) {
        addAdminInterest(newInt.id, newInt.name);
    }
}

let adminTimeout = null;
adminInput.addEventListener('input', (e) => {
    clearTimeout(adminTimeout);
    const val = e.target.value.trim();
    if(!val) {
        adminDropdown.classList.add('hidden');
        return;
    }
    
    adminTimeout = setTimeout(async () => {
        const res = await fetch(/api/interests?search=);
        const suggestions = await res.json();
        
        adminDropdown.innerHTML = '';
        let exactMatch = false;
        
        suggestions.forEach(s => {
            if(s.name.toLowerCase() === val.toLowerCase()) exactMatch = true;
            const item = document.createElement('div');
            item.className = "px-4 py-2 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer text-sm text-slate-700 dark:text-slate-300 flex items-center gap-2";
            item.innerHTML = <span class="text-slate-400">??</span> ;
            item.onclick = () => addAdminInterest(s.id, s.name);
            adminDropdown.appendChild(item);
        });
        
        if(!exactMatch) {
            const createItem = document.createElement('div');
            createItem.className = "px-4 py-2 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 cursor-pointer text-sm text-indigo-600 dark:text-indigo-400 font-medium border-t border-slate-100 dark:border-slate-700";
            createItem.innerHTML = + Add "";
            createItem.onclick = () => createAdminNewInterest(val);
            adminDropdown.appendChild(createItem);
        }
        
        adminDropdown.classList.remove('hidden');
    }, 300);
});

document.addEventListener('click', (e) => {
    if(!adminChipsContainer.contains(e.target)) {
        adminDropdown.classList.add('hidden');
    }
});
'''

# Insert the admin_chip_js script right before the closing </script> in admin.html
# Wait, I injected it right before </body>, so there is a </script> before </body>.
content = content.replace("</script>\n</body>", admin_chip_js + "\n</script>\n</body>")

# Remove old edit_interests references
content = re.sub(r"let intSelect = document\.getElementById\('edit_interests'\);.*?\}", "", content, flags=re.DOTALL)

with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated admin.html")
