import re

with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

script_block = '''
// Admin User Interests Chip Logic
let adminTargetUserId = null;
const adminInput = document.getElementById('admin-interest-input');
const adminDropdown = document.getElementById('admin-interest-dropdown');
const adminChipsContainer = document.getElementById('admin-interest-chips');
let adminActiveInterests = [];

async function loadAdminInterests() {
    if(!adminTargetUserId) return;
    const res = await fetch(/api/users//interests);
    adminActiveInterests = await res.json();
    renderAdminChips();
}

function renderAdminChips() {
    document.querySelectorAll('.admin-interest-chip').forEach(el => el.remove());
    adminActiveInterests.forEach(i => {
        const chip = document.createElement('div');
        chip.className = "admin-interest-chip flex items-center gap-1.5 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 px-3 py-1 rounded-full text-sm font-medium border border-indigo-100 dark:border-indigo-800";
        chip.innerHTML = 
            
            <button type="button" class="hover:text-indigo-900 dark:hover:text-white rounded-full p-0.5 transition-colors focus:outline-none" onclick="removeAdminInterest()">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        ;
        adminChipsContainer.insertBefore(chip, adminChipsContainer.firstElementChild);
    });
}

async function addAdminInterest(id, name) {
    if(!adminTargetUserId) return;
    if(adminActiveInterests.some(i => i.id === id)) return;
    await fetch(/api/users//interests, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_id: id})
    });
    adminInput.value = '';
    adminDropdown.classList.add('hidden');
    loadAdminInterests();
}

async function createNewAdminInterest(name) {
    const res = await fetch(/api/interests, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_name: name})
    });
    const data = await res.json();
    if(data.id) {
        addAdminInterest(data.id, data.name);
    }
}

async function removeAdminInterest(id) {
    if(!adminTargetUserId) return;
    await fetch(/api/users//interests/, { method: 'DELETE' });
    loadAdminInterests();
}

let adminTimeout;
if(adminInput) {
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
                item.innerHTML = <span class="text-slate-400">#</span> ;
                item.onclick = () => addAdminInterest(s.id, s.name);
                adminDropdown.appendChild(item);
            });
            
            if(!exactMatch) {
                const createItem = document.createElement('div');
                createItem.className = "px-4 py-2 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 cursor-pointer text-sm text-indigo-600 dark:text-indigo-400 font-medium border-t border-slate-100 dark:border-slate-700";
                createItem.innerHTML = + Add "";
                createItem.onclick = () => createNewAdminInterest(val);
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
}
'''

content = re.sub(r'// Admin User Interests Chip Logic.*?\}\n\}\n', script_block, content, flags=re.DOTALL)
with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("admin.html script patched.")
