import sys

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Locate the Hamburger Button
start_marker = "{% if user %}\n                  <!-- Hamburger Menu Button -->"
end_marker = "</button>\n                  {% endif %}"

if start_marker in content and end_marker in content:
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker, start_idx) + len(end_marker)
    
    hamburger_html = content[start_idx:end_idx]
    
    # Remove from original position
    content = content[:start_idx] + content[end_idx:]
    
    # Fix the margin class for extreme left alignment
    hamburger_html = hamburger_html.replace('mr-1', '-ml-2')
    
    # Insert before the logo
    logo_marker = "<!-- Materialized Logo & Home -->"
    insert_idx = content.find(logo_marker)
    
    if insert_idx != -1:
        content = content[:insert_idx] + hamburger_html + '\n                  ' + content[insert_idx:]
        
    with open('templates/base.html', 'w', encoding='utf-8') as f:
        f.write(content)
        print("Hamburger moved successfully.")
else:
    print("Hamburger button not found.")
