import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add the main tags back around the block content and flash messages!
if '<main ' not in content:
    # Let's find the closing header tag
    header_end = content.find('</header>') + 9
    script_start = content.find('<script>', header_end)
    
    # Everything in between header and script is the main body + flashes
    body_content = content[header_end:script_start]
    
    # We will just replace it with a properly wrapped <main>
    new_body = '''
    <!-- Main Content -->
    <main class="max-w-6xl mx-auto px-6 pb-12 pt-4 relative z-10 flex-grow w-full">
        {% if impersonating %}
        <div class="glass-panel p-4 mb-6 flex justify-between items-center bg-yellow-50/20 dark:bg-yellow-900/20 border-yellow-200/50 dark:border-yellow-700/50">
            <span class="text-slate-800 dark:text-slate-200">Viewing as <strong class="font-bold">{{ user }}</strong></span>
            <a href="{{ url_for('exit_view') }}" class="text-indigo-600 dark:text-indigo-400 hover:underline font-semibold">Exit view</a>
        </div>
        {% endif %}

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="mb-8 space-y-3">
                {% for message in messages %}
                    <div class="bg-green-100/50 dark:bg-green-900/40 text-green-800 dark:text-green-300 px-5 py-4 rounded-2xl border border-green-200/50 dark:border-green-800/50 font-medium backdrop-blur-md">
                        {{ message }}
                    </div>
                {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </main>
'''
    content = content[:header_end] + new_body + content[script_start:]
    
    with open('templates/base.html', 'w', encoding='utf-8') as f:
        f.write(content)
