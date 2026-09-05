import re

with open('d:/apps/templates/profile.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = '''                <div class="md:col-span-2">
                    <label class="form-label">Interests</label>
                    <select name="interests" multiple class="form-input h-24 int-select">
                        {% set user_ints = (user_data.interest_ids or '').split(',') %}
                        {% for i in master_interests %}
                        <option value="{{ i.id }}" {% if i.id|string in user_ints %}selected{% endif %}>{{ i.name }}</option>
                        {% endfor %}
                    </select>
                    <p class="text-[10px] text-slate-400 mt-1">Hold Ctrl (or Cmd) to select multiple interests.</p>
                </div>'''

new_block = '''                <div class="md:col-span-2 relative" id="interest-container" data-userid="{{ user_data.id }}">
                    <label class="form-label">Interests</label>
                    <div class="form-input flex flex-wrap gap-2 items-center min-h-[42px] p-2" id="interest-chips" style="height: auto;">
                        <div class="flex-1 min-w-[200px] relative">
                            <input type="text" id="interest-input" class="w-full bg-transparent border-none focus:ring-0 text-sm p-0 m-0 outline-none dark:text-white" placeholder="Type to search or add an interest..." autocomplete="off">
                            <div id="interest-dropdown" class="absolute left-0 right-0 top-full mt-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl z-50 hidden max-h-60 overflow-y-auto">
                            </div>
                        </div>
                    </div>
                </div>'''

content = content.replace(old_block, new_block)

js_block = '''<script>
const userId = document.getElementById('interest-container').dataset.userid;
const input = document.getElementById('interest-input');
const dropdown = document.getElementById('interest-dropdown');
const chipsContainer = document.getElementById('interest-chips');
let activeInterests = [];

async function loadInterests() {
    const res = await fetch(/api/users//interests);
    activeInterests = await res.json();
    renderChips();
}

function renderChips() {
    // Remove old chips
    document.querySelectorAll('.interest-chip').forEach(e => e.remove());
    // Insert new chips before the input wrapper
    const inputWrapper = input.parentElement;
    activeInterests.forEach(i => {
        const chip = document.createElement('span');
        chip.className = "interest-chip inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-300";
        chip.innerHTML = ${i.name} <button type="button" class="hover:text-indigo-900 dark:hover:text-indigo-100 ml-1" onclick="removeInterest()">&times;</button>;
        chipsContainer.insertBefore(chip, inputWrapper);
    });
}

async function removeInterest(interestId) {
    await fetch(/api/users//interests/, { method: 'DELETE' });
    activeInterests = activeInterests.filter(i => i.id !== interestId);
    renderChips();
}

async function addInterest(interestId, interestName) {
    dropdown.classList.add('hidden');
    input.value = '';
    
    // Check if it already exists in user's active
    if (activeInterests.find(i => i.id === interestId)) return;
    
    await fetch(/api/users//interests, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_id: interestId})
    });
    
    activeInterests.push({id: interestId, name: interestName});
    renderChips();
}

async function createNewInterest(name) {
    dropdown.classList.add('hidden');
    input.value = '';
    
    const res = await fetch('/api/interests', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interest_name: name})
    });
    const newInt = await res.json();
    if(newInt.id) {
        addInterest(newInt.id, newInt.name);
    }
}

let timeout = null;
input.addEventListener('input', (e) => {
    clearTimeout(timeout);
    const val = e.target.value.trim();
    if(!val) {
        dropdown.classList.add('hidden');
        return;
    }
    
    timeout = setTimeout(async () => {
        const res = await fetch(/api/interests?search=);
        const suggestions = await res.json();
        
        dropdown.innerHTML = '';
        let exactMatch = false;
        
        suggestions.forEach(s => {
            if(s.name.toLowerCase() === val.toLowerCase()) exactMatch = true;
            const item = document.createElement('div');
            item.className = "px-4 py-2 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer text-sm text-slate-700 dark:text-slate-300 flex items-center gap-2";
            item.innerHTML = <span class="text-slate-400">??</span> ;
            item.onclick = () => addInterest(s.id, s.name);
            dropdown.appendChild(item);
        });
        
        if(!exactMatch) {
            const createItem = document.createElement('div');
            createItem.className = "px-4 py-2 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 cursor-pointer text-sm text-indigo-600 dark:text-indigo-400 font-medium border-t border-slate-100 dark:border-slate-700";
            createItem.innerHTML = + Add "";
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
'''

content = content.replace('{% endblock %}', js_block + '\n{% endblock %}')

with open('d:/apps/templates/profile.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated profile.html")
