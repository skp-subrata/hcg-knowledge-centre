import re
with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

# I will precisely match the HTML to remove from the Add User form.
target = """                <div class="md:col-span-2">
                    <label class="form-label flex justify-between">Interests <a href="#" onclick="addMaster('interests', this)" class="text-indigo-500 hover:underline text-[10px]">[+ Add Interest]</a></label>
                    <select name="interests" multiple class="form-input h-24 int-select">
                        {% for i in master_interests %}
                        <option value="{{ i.id }}">{{ i.name }}</option>
                        {% endfor %}
                    </select>
                    <p class="text-[10px] text-slate-400 mt-1">Hold Ctrl (or Cmd) to select multiple interests.</p>
                </div>
                <div class="md:col-span-2">
                    <label class="form-label">About Me</label>
                    <textarea name="about_me" class="form-input h-24" placeholder="Short professional or personal introduction"></textarea>
                </div>"""

# Ensure exact whitespace matching by using a regex sub that handles variable whitespace if exact match fails
if target in content:
    content = content.replace(target, '')
else:
    # If indentation is slightly different
    pattern = r'<div class="md:col-span-2">\s*<label class="form-label flex justify-between">Interests.*?<textarea name="about_me" class="form-input h-24" placeholder="Short professional or personal introduction"></textarea>\s*</div>'
    content = re.sub(pattern, '', content, flags=re.DOTALL)

with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Removed from Add User form!")
