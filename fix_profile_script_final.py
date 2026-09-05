with open('d:/apps/templates/profile.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_multi = '''                <div class="md:col-span-2">
                    <label class="form-label">Interests</label>
                    <select name="interests" multiple class="form-input h-24 int-select">
                        {% set user_ints = (user_data.interest_ids or '').split(',') %}
                        {% for i in master_interests %}
                        <option value="{{ i.id }}" {% if i.id|string in user_ints %}selected{% endif %}>{{ i.name }}</option>
                        {% endfor %}
                    </select>
                    <p class="text-[10px] text-slate-400 mt-1">Hold Ctrl (or Cmd) to select multiple interests.</p>
                </div>'''

new_chips = '''                <div class="md:col-span-2 relative" id="interest-container" data-userid="{{ user_data.id }}">
                    <label class="form-label">Interests</label>
                    <div class="form-input flex flex-wrap gap-2 items-center min-h-[42px] p-2" id="interest-chips" style="height: auto;">
                        <div class="flex-1 min-w-[200px] relative">
                            <input type="text" id="interest-input" class="w-full bg-transparent border-none focus:ring-0 text-sm p-0 m-0 outline-none dark:text-white" placeholder="Type to search or add an interest..." autocomplete="off">
                            <div id="interest-dropdown" class="absolute left-0 right-0 top-full mt-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl z-50 hidden max-h-60 overflow-y-auto">
                            </div>
                        </div>
                    </div>
                </div>'''

if old_multi in content:
    content = content.replace(old_multi, new_chips)
else:
    print("WARNING: Could not find old multi select.")

script_block = '''<script>
const userId = document.getElementById('interest-container').dataset.userid;
const input = document.getElementById('interest-input');
const dropdown = document.getElementById('interest-dropdown');
const chipsContainer = document.getElementById('interest-chips');
let activeInterests = [];

async function loadInterests() {
    const res = await fetch(`/api/users/${userId}/interests`);
    activeInterests = await res.json();
    renderChips();
}

function renderChips() {
    document.querySelectorAll('.interest-chip').forEach(el => el.remove());
    activeInterests.forEach(i => {
        const chip = document.createElement('div');
        chip.className = "interest-chip flex items-center gap-1.5 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 px-3 py-1 rounded-full text-sm font-medium border border-indigo-100 dark:border-indigo-800";
        chip.innerHTML = `
            ${i.name}
            <button type="button" class="hover:text-indigo-900 dark:hover:text-white rounded-full p-0.5 transition-colors focus:outline-none" onclick="removeInterest(${i.id})">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        `;
        chipsContainer.insertBefore(chip, chipsContainer.firstElementChild);
    });
}

async function addInterest(id, name) {
    if(activeInterests.some(i => i.id === id)) return;
    await fetch(`/api/users/${userId}/interests`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_id: id})
    });
    input.value = '';
    dropdown.classList.add('hidden');
    loadInterests();
}

async function createNewInterest(name) {
    const res = await fetch(`/api/interests`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_name: name})
    });
    const data = await res.json();
    if(data.id) {
        addInterest(data.id, data.name);
    }
}

async function removeInterest(id) {
    await fetch(`/api/users/${userId}/interests/${id}`, { method: 'DELETE' });
    loadInterests();
}

let timeout;
input.addEventListener('input', (e) => {
    clearTimeout(timeout);
    const val = e.target.value.trim();
    if(!val) {
        dropdown.classList.add('hidden');
        return;
    }
    
    timeout = setTimeout(async () => {
        const res = await fetch(`/api/interests?search=${val}`);
        const suggestions = await res.json();
        
        dropdown.innerHTML = '';
        let exactMatch = false;
        
        suggestions.forEach(s => {
            if(s.name.toLowerCase() === val.toLowerCase()) exactMatch = true;
            const item = document.createElement('div');
            item.className = "px-4 py-2 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer text-sm text-slate-700 dark:text-slate-300 flex items-center gap-2";
            item.innerHTML = `<span class="text-slate-400">#</span> ${s.name}`;
            item.onclick = () => addInterest(s.id, s.name);
            dropdown.appendChild(item);
        });
        
        if(!exactMatch) {
            const createItem = document.createElement('div');
            createItem.className = "px-4 py-2 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 cursor-pointer text-sm text-indigo-600 dark:text-indigo-400 font-medium border-t border-slate-100 dark:border-slate-700";
            createItem.innerHTML = `+ Add "${val}"`;
            createItem.onclick = () => createNewInterest(val);
            dropdown.appendChild(createItem);
        }
        
        dropdown.classList.remove('hidden');
    }, 300);
});

// Close dropdown on click outside
document.addEventListener('click', (e) => {
    if(!chipsContainer.contains(e.target)) {
        dropdown.classList.add('hidden');
    }
});

loadInterests();
</script>
{% endblock %}
'''

content = content.replace('{% endblock %}', script_block)

with open('d:/apps/templates/profile.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS: profile.html correctly updated!")
