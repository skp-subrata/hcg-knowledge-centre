with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

edit_user_modal = """
<!-- Edit User Modal -->
<div id="editUserModal" class="fixed inset-0 z-[100] hidden flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
    <div class="bg-white dark:bg-slate-900 rounded-2xl max-w-2xl w-full shadow-2xl relative my-auto">
        <button onclick="document.getElementById('editUserModal').classList.add('hidden')" type="button" class="absolute top-4 right-4 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
        <div class="p-6">
            <h2 class="text-xl font-semibold text-slate-900 dark:text-white mb-6">Edit User Data</h2>
            <form method="post" id="editUserForm">
                <input type="hidden" name="action" value="update_user">
                <input type="hidden" name="record_id" id="edit_record_id">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label class="form-label">Full name *</label>
                        <input name="full_name" id="edit_full_name" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">Username *</label>
                        <input name="username" id="edit_username" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">Employee ID *</label>
                        <input name="employee_id" id="edit_employee_id" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">Email ID *</label>
                        <input name="email" id="edit_email" type="email" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">Phone Number *</label>
                        <input name="phone_number" id="edit_phone_number" type="tel" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">Role / Permission *</label>
                        <select name="role" id="edit_role" class="form-input">
                            {% for option in roles %}<option value="{{ option }}">{{ option|title }}</option>{% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="form-label flex justify-between">Department <a href="#" onclick="addMaster('departments', this)" class="text-indigo-500 hover:underline text-[10px]">[+ Add Department]</a></label>
                        <select name="department_id" id="edit_department_id" class="form-input dept-select">
                            <option value="">[ Select Department - ]</option>
                            {% for d in master_depts %}
                            <option value="{{ d.id }}">{{ d.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="form-label flex justify-between">Position <a href="#" onclick="addMaster('positions', this)" class="text-indigo-500 hover:underline text-[10px]">[+ Add Position]</a></label>
                        <select name="position_id" id="edit_position_id" class="form-input pos-select">
                            <option value="">[ Select Position - ]</option>
                            {% for p in master_positions %}
                            <option value="{{ p.id }}">{{ p.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="form-label">Location</label>
                        <input name="location" id="edit_location" class="form-input">
                    </div>
                    <div class="md:col-span-2">
                        <label class="form-label flex justify-between">Interests <a href="#" onclick="addMaster('interests', this)" class="text-indigo-500 hover:underline text-[10px]">[+ Add Interest]</a></label>
                        <select name="interests" id="edit_interests" multiple class="form-input h-24 int-select">
                            {% for i in master_interests %}
                            <option value="{{ i.id }}">{{ i.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="md:col-span-2">
                        <label class="form-label">About Me</label>
                        <textarea name="about_me" id="edit_about_me" class="form-input h-24" placeholder="Short professional or personal introduction"></textarea>
                    </div>
                </div>
                <button type="submit" class="btn-primary w-full mt-6">Save Changes</button>
            </form>
        </div>
    </div>
</div>

<script>
function openEditUserModal(user) {
    document.getElementById('edit_record_id').value = user.id || '';
    document.getElementById('edit_full_name').value = user.full_name || '';
    document.getElementById('edit_username').value = user.username || '';
    document.getElementById('edit_employee_id').value = user.employee_id || '';
    document.getElementById('edit_email').value = user.email || '';
    document.getElementById('edit_phone_number').value = user.phone_number || '';
    document.getElementById('edit_role').value = user.role || 'basic user';
    document.getElementById('edit_department_id').value = user.department_id || '';
    document.getElementById('edit_position_id').value = user.position_id || '';
    document.getElementById('edit_location').value = user.location || '';
    document.getElementById('edit_about_me').value = user.about_me || '';
    
    // Set multi-select for interests
    let intSelect = document.getElementById('edit_interests');
    let intIds = (user.interest_ids || '').split(',');
    for (let i = 0; i < intSelect.options.length; i++) {
        intSelect.options[i].selected = intIds.includes(intSelect.options[i].value);
    }
    
    document.getElementById('editUserModal').classList.remove('hidden');
}

async function addMaster(type, el) {
    let name = prompt("Enter new " + type.slice(0, -1) + " name:");
    if (!name) return;
    
    let res = await fetch('/api/v1/' + type, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
    let data = await res.json();
    if (res.ok) {
        // Find all selects matching this type and add the option
        let classTarget = type === 'departments' ? '.dept-select' : (type === 'positions' ? '.pos-select' : '.int-select');
        let selects = document.querySelectorAll(classTarget);
        selects.forEach(select => {
            let opt = document.createElement('option');
            opt.value = data.id;
            opt.textContent = data.name;
            select.appendChild(opt);
            // If it was the specific element clicked near, select it
            if (el && el.parentElement && el.parentElement.nextElementSibling === select) {
                if (select.multiple) { opt.selected = true; }
                else { select.value = data.id; }
            }
        });
        alert(data.message);
    } else {
        alert(data.error);
    }
}
</script>
"""

content = content.replace("{% endblock %}", edit_user_modal + "\n{% endblock %}")

with open("d:/apps/templates/admin.html", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated admin.html with edit user modal")
