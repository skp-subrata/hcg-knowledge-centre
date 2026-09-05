with open('d:/apps/templates/admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

releases_section = """
    <!-- ?? APP RELEASES TABLE ?? -->
    {% if role == 'admin' %}
    <section class="glass-panel p-6 overflow-hidden" id="releases-section">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5 border-b border-slate-200 dark:border-slate-800 pb-4">
            <div>
                <h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">Application Releases</h2>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">Manage version history and release notes.</p>
            </div>
            <button onclick="document.getElementById('createReleaseModal').classList.remove('hidden')" class="btn-primary text-xs px-4 py-2 rounded-xl flex items-center gap-1.5 font-semibold">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                Create Release
            </button>
        </div>
        
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="border-b border-slate-200 dark:border-slate-800">
                        <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Version</th>
                        <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Title</th>
                        <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider">Date</th>
                        <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider text-center">Status</th>
                        <th class="p-3 font-bold text-slate-500 dark:text-slate-400 uppercase text-xs tracking-wider text-right">Actions</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                    {% for item in releases %}
                    <tr class="hover:bg-white/30 dark:hover:bg-white/5 transition">
                        <td class="p-3 font-bold">{{ item.version_number }}</td>
                        <td class="p-3 text-slate-700 dark:text-slate-300">{{ item.release_title }}</td>
                        <td class="p-3 text-slate-500 dark:text-slate-400 text-sm">{{ item.release_date.split(' ')[0] if item.release_date else '-' }}</td>
                        <td class="p-3 text-center">
                            {% if item.is_active %}
                            <span class="px-2 py-1 rounded-full text-xs font-bold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">Active</span>
                            {% else %}
                            <span class="px-2 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">Inactive</span>
                            {% endif %}
                        </td>
                        <td class="p-3 text-right space-x-2">
                            {% if not item.is_active %}
                            <form class="inline" method="post" action="{{ url_for('admin_panel') }}#releases-section">
                                <input type="hidden" name="action" value="set_active_release">
                                <input type="hidden" name="record_id" value="{{ item.id }}">
                                <button type="submit" class="text-xs font-semibold text-green-600 dark:text-green-400 hover:underline">Publish</button>
                            </form>
                            {% endif %}
                            <button type="button" onclick='openEditReleaseModal({{ item|tojson }})' class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">Edit</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </section>

    <!-- Create/Edit Release Modals -->
    <div id="createReleaseModal" class="fixed inset-0 z-[100] hidden flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
        <div class="bg-white dark:bg-slate-900 rounded-2xl max-w-2xl w-full shadow-2xl relative my-auto">
            <button onclick="document.getElementById('createReleaseModal').classList.add('hidden')" type="button" class="absolute top-4 right-4 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full">&times;</button>
            <div class="p-6">
                <h2 class="text-xl font-semibold mb-6">Create New Release</h2>
                <form method="post" action="{{ url_for('admin_panel') }}#releases-section">
                    <input type="hidden" name="action" value="create_release">
                    <div class="space-y-4">
                        <div><label class="form-label">Version Number (e.g. 1.6.0)</label><input name="version_number" class="form-input" required></div>
                        <div><label class="form-label">Release Title</label><input name="release_title" class="form-input" required></div>
                        <div><label class="form-label">Features (JSON Array of strings)</label><textarea name="features" class="form-input h-20" placeholder='["Feature 1", "Feature 2"]'></textarea></div>
                        <div><label class="form-label">Improvements (JSON Array of strings)</label><textarea name="improvements" class="form-input h-20" placeholder='["Improvement 1"]'></textarea></div>
                        <div><label class="form-label">Bug Fixes (JSON Array of strings)</label><textarea name="bug_fixes" class="form-input h-20" placeholder='["Fix 1"]'></textarea></div>
                    </div>
                    <button type="submit" class="btn-primary w-full mt-6">Create Release</button>
                </form>
            </div>
        </div>
    </div>

    <div id="editReleaseModal" class="fixed inset-0 z-[100] hidden flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
        <div class="bg-white dark:bg-slate-900 rounded-2xl max-w-2xl w-full shadow-2xl relative my-auto">
            <button onclick="document.getElementById('editReleaseModal').classList.add('hidden')" type="button" class="absolute top-4 right-4 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full">&times;</button>
            <div class="p-6">
                <h2 class="text-xl font-semibold mb-6">Edit Release Notes</h2>
                <form method="post" action="{{ url_for('admin_panel') }}#releases-section">
                    <input type="hidden" name="action" value="update_release">
                    <input type="hidden" name="record_id" id="edit_rel_id">
                    <div class="space-y-4">
                        <div><label class="form-label">Release Title</label><input name="release_title" id="edit_rel_title" class="form-input" required></div>
                        <div><label class="form-label">Features (JSON Array)</label><textarea name="features" id="edit_rel_feat" class="form-input h-20"></textarea></div>
                        <div><label class="form-label">Improvements (JSON Array)</label><textarea name="improvements" id="edit_rel_imp" class="form-input h-20"></textarea></div>
                        <div><label class="form-label">Bug Fixes (JSON Array)</label><textarea name="bug_fixes" id="edit_rel_bug" class="form-input h-20"></textarea></div>
                    </div>
                    <button type="submit" class="btn-primary w-full mt-6">Save Changes</button>
                </form>
            </div>
        </div>
    </div>

    <script>
    function openEditReleaseModal(rel) {
        document.getElementById('edit_rel_id').value = rel.id;
        document.getElementById('edit_rel_title').value = rel.release_title || '';
        document.getElementById('edit_rel_feat').value = rel.features || '[]';
        document.getElementById('edit_rel_imp').value = rel.improvements || '[]';
        document.getElementById('edit_rel_bug').value = rel.bug_fixes || '[]';
        document.getElementById('editReleaseModal').classList.remove('hidden');
    }
    </script>
    {% endif %}
"""

if "<!-- ?? APP RELEASES TABLE ?? -->" not in content:
    content = content.replace("<!--  ? ? ? API CREDENTIALS TABLE  ? ? ? -->", releases_section + "\n\n    <!--  ? ? ? API CREDENTIALS TABLE  ? ? ? -->")


with open('d:/apps/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS: Added App Releases to admin.html")
