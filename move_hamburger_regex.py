import sys
import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'\s*{% if user %}\s*<!-- Hamburger Menu Button -->\s*<button id="menu-btn".*?</button>\s*{% endif %}\s*'
match = re.search(pattern, content, flags=re.DOTALL)

if match:
    hamburger_html = match.group(0)
    
    # Remove it from the current location
    content = content.replace(hamburger_html, '\n')
    
    # Clean up the html a bit and fix margins
    clean_html = hamburger_html.strip() + '\n                  '
    clean_html = clean_html.replace('mr-1', '-ml-2')
    
    # Find the logo
    logo_marker = "<!-- Materialized Logo & Home -->"
    insert_idx = content.find(logo_marker)
    
    if insert_idx != -1:
        # Insert it before the logo
        content = content[:insert_idx] + clean_html + content[insert_idx:]
        
        with open('templates/base.html', 'w', encoding='utf-8') as f:
            f.write(content)
        print("Moved successfully.")
else:
    print("Not found.")
