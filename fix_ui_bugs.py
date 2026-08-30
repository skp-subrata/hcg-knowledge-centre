import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Extract the hamburger button
hamburger_btn = '''                {% if user %}
                <!-- Hamburger Menu Button -->
                <button id="menu-btn" class="p-2 -ml-2 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400">
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-slate-700 dark:text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                </button>
                {% endif %}'''

if hamburger_btn in content:
    content = content.replace(hamburger_btn + '\n', '')
    content = content.replace(hamburger_btn, '')

# 2. Insert the hamburger button right before the profile dropdown
profile_dropdown = '''                {% if user %}
                <!-- Profile Dropdown -->'''
new_profile_section = hamburger_btn.replace('-ml-2', 'mr-1') + '\n\n' + profile_dropdown

if profile_dropdown in content:
    content = content.replace(profile_dropdown, new_profile_section)


# 3. Extract the drawer and overlay
# We need to find the exact block for the drawer
drawer_start_marker = '{% if user %}\n        <!-- Offcanvas Hamburger Menu (Drawer) -->'
drawer_end_marker = '        </div>\n        {% endif %}\n    </header>'

if drawer_start_marker in content and drawer_end_marker in content:
    drawer_start = content.find(drawer_start_marker)
    drawer_end = content.find(drawer_end_marker) + len('        </div>\n        {% endif %}')
    
    drawer_content = content[drawer_start:drawer_end]
    
    # Remove it from header
    content = content[:drawer_start] + content[drawer_end:]
    
    # Append it right before <script>
    script_start = content.rfind('<script>')
    content = content[:script_start] + drawer_content + '\n' + content[script_start:]


# 4. Fix the Profile Dropdown JS logic
old_js = '''        if (profileBtn && profileMenu) {
            profileBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                profileMenu.classList.toggle('hidden');
                setTimeout(() => {
                    profileMenu.classList.toggle('opacity-0');
                    profileMenu.classList.toggle('scale-95');
                }, 10);
            });
            
            // Close dropdown when clicking outside
            document.addEventListener('click', (e) => {
                if (!profileBtn.contains(e.target) && !profileMenu.contains(e.target) && !profileMenu.classList.contains('hidden')) {
                    profileMenu.classList.add('opacity-0', 'scale-95');
                    setTimeout(() => profileMenu.classList.add('hidden'), 200);
                }
            });
        }'''

new_js = '''        if (profileBtn && profileMenu) {
            profileBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (profileMenu.classList.contains('hidden')) {
                    profileMenu.classList.remove('hidden');
                    setTimeout(() => {
                        profileMenu.classList.remove('opacity-0', 'scale-95');
                    }, 10);
                } else {
                    profileMenu.classList.add('opacity-0', 'scale-95');
                    setTimeout(() => {
                        profileMenu.classList.add('hidden');
                    }, 200);
                }
            });
            
            // Close dropdown when clicking outside
            document.addEventListener('click', (e) => {
                if (!profileBtn.contains(e.target) && !profileMenu.contains(e.target) && !profileMenu.classList.contains('hidden')) {
                    profileMenu.classList.add('opacity-0', 'scale-95');
                    setTimeout(() => profileMenu.classList.add('hidden'), 200);
                }
            });
            // Stop clicks inside the menu from propagating to document
            profileMenu.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        }'''

if old_js in content:
    content = content.replace(old_js, new_js)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
