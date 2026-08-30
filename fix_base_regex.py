import sys
import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

dropdown_new = '''                  <!-- Profile Dropdown -->
                  <div class="relative">
                      <button id="profile-btn" class="flex items-center justify-center w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-800 hover:ring-2 ring-indigo-500 transition-all focus:outline-none overflow-hidden border border-slate-300 dark:border-slate-700 bg-cover bg-center" {% if profile_picture %}style="background-image: url('/uploads/{{ profile_picture }}')"{% endif %}>
                          {% if not profile_picture %}
                          <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-slate-600 dark:text-slate-300 mt-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                          {% endif %}
                      </button>
                      <!-- Dropdown Menu -->
                      <div id="profile-menu" class="hidden absolute right-0 mt-2 w-56 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg py-1 z-50">
                          <div class="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/50">
                              <p class="text-sm font-semibold text-slate-900 dark:text-slate-50 truncate">{{ user }}</p>
                              <p class="text-xs text-slate-500 dark:text-slate-400 capitalize">{{ role }} {% if actual_role and actual_role != 'basic user' and role == 'basic user' %}(Admin){% endif %}</p>
                          </div>
                          
                          <a href="{{ url_for('profile') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                              <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                              Edit Profile
                          </a>
                          
                          {% if actual_role in ('admin', 'moderator') and not impersonating %}
                              {% if role == 'basic user' %}
                              <a href="{{ url_for('switch_role') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                                  <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                                  Switch to Admin
                              </a>
                              {% else %}
                              <a href="{{ url_for('switch_role') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                                  <svg class="w-4 h-4 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 14l9-5-9-5-9 5 9 5z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z"></path></svg>
                                  Switch to Student
                              </a>
                              {% endif %}
                          {% endif %}
                          
                          {% if impersonating %}
                          <a href="{{ url_for('exit_view') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm text-yellow-600 dark:text-yellow-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 15l-3-3m0 0l3-3m-3 3h8M3 12a9 9 0 1118 0 9 9 0 01-18 0z"></path></svg>
                              Exit View
                          </a>
                          {% endif %}

                          <a href="{{ url_for('logout') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>
                              Log out
                          </a>
                      </div>
                  </div>'''

pattern = r'<!-- Profile Dropdown -->.*?</div>\s*</div>'
content = re.sub(pattern, dropdown_new, content, flags=re.DOTALL)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
