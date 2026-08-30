import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_login = '''                    profile_picture=user.get("profile_picture", "")'''
new_login = '''                    profile_picture=user["profile_picture"] if "profile_picture" in user.keys() else ""'''

content = content.replace(old_login, new_login)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
