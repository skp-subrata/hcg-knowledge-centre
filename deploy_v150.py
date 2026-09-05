import re
with open('d:/apps/templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update the sidebar versions
content = content.replace("v1.3.3", "v1.4.0")
content = content.replace(">v1.4.0<", ">v1.5.0<")

# 2. Update the JS constant
content = content.replace("const CURRENT_VERSION = 'v1.4.0';", "const CURRENT_VERSION = 'v1.5.0';")

# 3. Add the release notes block
new_notes = """                    <div>
                        <h4 class="text-sm font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 flex items-center gap-2 mb-3">
                            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800/40">Latest</span>
                            v1.5.0 Update
                        </h4>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
                            <div class="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800/50 shadow-sm flex items-start gap-3">
                                <div class="p-2 rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400 shrink-0">
                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                                </div>
                                <div>
                                    <h5 class="font-bold text-slate-800 dark:text-slate-200 mb-1 text-sm">Interactive Profile Customization</h5>
                                    <p class="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">Profiles now feature an interactive Interest Chip UI. Admins can manage a centralized master list of interests.</p>
                                </div>
                            </div>
                            <div class="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800/50 shadow-sm flex items-start gap-3">
                                <div class="p-2 rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-900/30 dark:text-sky-400 shrink-0">
                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>
                                </div>
                                <div>
                                    <h5 class="font-bold text-slate-800 dark:text-slate-200 mb-1 text-sm">Admin Workflow Upgrades</h5>
                                    <p class="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">The "Edit User" wizard has been restored, and "Add User" form streamlined for a smoother administrative experience.</p>
                                </div>
                            </div>
                        </div>

                        <div class="opacity-75">
<h4 class="text-sm font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 flex items-center gap-2 mb-3">
                            v1.4.0 Update"""

content = content.replace("""                    <div>
                        <h4 class="text-sm font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 flex items-center gap-2 mb-3">
                            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800/40">Latest</span>
                            v1.4.0 Update""", new_notes)

with open('d:/apps/templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Updated version to v1.5.0 and added release notes")
