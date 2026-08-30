import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if '# Migrate users table for profile fields' in line:
        skip = True
        continue
    
    if skip and 'PRAGMA foreign_keys = OFF' in line:
        skip = False
        new_lines.append('\t\t\t\tconnection.execute("PRAGMA foreign_keys = OFF")\n')
        continue
        
    if skip:
        continue
        
    new_lines.append(line)

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

