with open('d:/apps/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix references in SELECT queries
content = content.replace('LEFT JOIN user_interests ui', 'LEFT JOIN user_interest ui')
content = content.replace('INSERT INTO user_interests', 'INSERT INTO user_interest')
content = content.replace('INSERT OR IGNORE INTO user_interests', 'INSERT OR IGNORE INTO user_interest')
content = content.replace('DELETE FROM user_interests', 'DELETE FROM user_interest')
content = content.replace('FROM interests WHERE', "FROM interest_master WHERE")
content = content.replace('SELECT id, name FROM interests', 'SELECT id, interest_name as name FROM interest_master')

# Remove the old profile POST logic for interests
old_profile_logic = '''				connection.execute("DELETE FROM user_interest WHERE user_id = ?", (session["user_id"],))
				for int_id in interests:
					connection.execute("INSERT OR IGNORE INTO user_interest (user_id, interest_id) VALUES (?, ?)", (session["user_id"], int_id))'''
content = content.replace(old_profile_logic, '')

old_admin_logic_1 = '''								connection.execute("DELETE FROM user_interest WHERE user_id = ?", (user_id,))
								for int_id in interests:
									connection.execute("INSERT OR IGNORE INTO user_interest (user_id, interest_id) VALUES (?, ?)", (user_id, int_id))'''
content = content.replace(old_admin_logic_1, '')

old_admin_logic_2 = '''								for int_id in interests:
									connection.execute("INSERT OR IGNORE INTO user_interest (user_id, interest_id) VALUES (?, ?)", (new_user_id, int_id))'''
content = content.replace(old_admin_logic_2, '')

with open('d:/apps/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated remaining backend references.")
