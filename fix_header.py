import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

header_start = content.find('<!-- Navbar -->')
main_start = content.find('<!-- Main Content -->')

new_header = '''<!-- Navbar -->
    <header class="sticky top-0 z-50 w-full border-b border-border/40 dark:border-darkBorder/40 bg-background/95 dark:bg-darkBackground/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 dark:supports-[backdrop-filter]:bg-darkBackground/60">
        <nav class="max-w-6xl mx-auto px-6 h-16 flex justify-between items-center relative">
            
            <div class="flex items-center gap-4">
                {% if user %}
                <!-- Hamburger Menu Button -->
                <button id="menu-btn" class="p-2 -ml-2 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400">
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-slate-700 dark:text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                </button>
                {% endif %}

                <!-- Materialized Logo & Home -->
                <a class="text-xl font-bold tracking-tight flex items-center gap-2" href="{{ url_for('home') }}">
                    <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-md">
                        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
                            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
                        </svg>
                    </div>
                    <span class="text-slate-900 dark:text-slate-50 hidden sm:block">HCG</span>
                    <span class="text-slate-600 dark:text-slate-400 font-medium hidden sm:block">Knowledge Centre</span>
                </a>
            </div>

            <div class="flex items-center gap-3 sm:gap-4 text-sm font-medium text-slate-600 dark:text-slate-400">
                <button id="themeToggle" type="button" class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 dark:border-slate-800 bg-transparent hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="hidden dark:block"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="block dark:hidden"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>
                    <span class="sr-only">Toggle theme</span>
                </button>

                {% if user %}
                <!-- Profile Dropdown -->
                <div class="relative">
                    <button id="profile-btn" class="flex items-center justify-center w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-800 hover:ring-2 ring-indigo-500 transition-all focus:outline-none overflow-hidden border border-slate-300 dark:border-slate-700">
                        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-slate-600 dark:text-slate-300 mt-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                    </button>
                    <!-- Dropdown Menu -->
                    <div id="profile-menu" class="hidden absolute right-0 mt-2 w-56 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg py-1 z-50">
                        <div class="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/50">
                            <p class="text-sm font-semibold text-slate-900 dark:text-slate-50 truncate">{{ user }}</p>
                            <p class="text-xs text-slate-500 dark:text-slate-400 capitalize">{{ role }}</p>
                        </div>
                        
                        {% if role in ('admin', 'moderator') and not impersonating %}
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors">
                            <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                            Switch Role / Admin
                        </a>
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
                </div>
                {% endif %}
            </div>
        </nav>
        
        {% if user %}
        <!-- Offcanvas Hamburger Menu (Drawer) -->
        <div id="side-menu-overlay" class="fixed inset-0 bg-slate-900/40 dark:bg-slate-950/60 backdrop-blur-sm z-[55] hidden opacity-0 transition-opacity duration-300"></div>
        <div id="side-menu" class="fixed top-0 left-0 w-72 h-full bg-white dark:bg-slate-950 border-r border-slate-200 dark:border-slate-800 shadow-2xl z-[60] transform -translate-x-full transition-transform duration-300 flex flex-col">
            <div class="p-5 border-b border-slate-200 dark:border-slate-800 flex justify-between items-center bg-slate-50/50 dark:bg-slate-900/50">
                <span class="font-bold text-lg text-slate-900 dark:text-slate-50 flex items-center gap-2">
                    <div class="flex items-center justify-center w-7 h-7 rounded bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow">
                        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
                            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
                        </svg>
                    </div>
                    Navigation
                </span>
                <button id="close-menu-btn" class="p-1 rounded-md hover:bg-slate-200 dark:hover:bg-slate-800 transition-colors text-slate-500">
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            
            <div class="p-4 overflow-y-auto flex-grow">
                <ul class="space-y-1">
                    <li>
                        <a href="{{ url_for('home') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                            Dashboard
                        </a>
                    </li>
                    
                    {% if role in ('admin', 'moderator') %}
                    <li class="pt-6 pb-2">
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">Courses</p>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                            Create Course
                        </a>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                            Edit / Manage Courses
                        </a>
                    </li>
                    
                    <li class="pt-6 pb-2">
                        <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">Assessments</p>
                    </li>
                    <li>
                        <a href="{{ url_for('admin_panel') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium transition-colors">
                            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path></svg>
                            Manage Assessments
                        </a>
                    </li>
                    {% endif %}
                </ul>
            </div>
            
            <div class="p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
                <p class="text-[11px] text-slate-400 text-center font-medium">HCG Knowledge Centre &copy; 2026</p>
            </div>
        </div>
        {% endif %}
    </header>
'''

script_block = '''
    <script>
        // Dark mode setup
        const html = document.documentElement;
        const themeToggle = document.getElementById('themeToggle');
        const themeKey = 'learnly-theme';
        
        if (localStorage.getItem(themeKey) === 'dark' || (!localStorage.getItem(themeKey) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            html.classList.add('dark');
        } else {
            html.classList.remove('dark');
        }

        themeToggle.addEventListener('click', () => {
            html.classList.toggle('dark');
            localStorage.setItem(themeKey, html.classList.contains('dark') ? 'dark' : 'light');
        });

        // Profile Dropdown Toggle
        const profileBtn = document.getElementById('profile-btn');
        const profileMenu = document.getElementById('profile-menu');
        
        if (profileBtn && profileMenu) {
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
        }

        // Hamburger Menu (Drawer) Toggle
        const menuBtn = document.getElementById('menu-btn');
        const closeMenuBtn = document.getElementById('close-menu-btn');
        const sideMenu = document.getElementById('side-menu');
        const sideMenuOverlay = document.getElementById('side-menu-overlay');

        function openDrawer() {
            sideMenuOverlay.classList.remove('hidden');
            // Small delay to allow display:block to apply before transition
            setTimeout(() => {
                sideMenuOverlay.classList.remove('opacity-0');
                sideMenu.classList.remove('-translate-x-full');
            }, 10);
            document.body.style.overflow = 'hidden';
        }

        function closeDrawer() {
            sideMenuOverlay.classList.add('opacity-0');
            sideMenu.classList.add('-translate-x-full');
            setTimeout(() => {
                sideMenuOverlay.classList.add('hidden');
            }, 300);
            document.body.style.overflow = '';
        }

        if (menuBtn && sideMenu) {
            menuBtn.addEventListener('click', openDrawer);
            closeMenuBtn.addEventListener('click', closeDrawer);
            sideMenuOverlay.addEventListener('click', closeDrawer);
        }
    </script>
'''

new_content = content[:header_start] + new_header + content[main_start:content.find('<script>')] + script_block + content[content.rfind('</body>'):]

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Updated base.html successfully.")
