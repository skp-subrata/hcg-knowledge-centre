import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(', actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture"), actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture")', ', actual_role=session.get("actual_role"), profile_picture=session.get("profile_picture")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
