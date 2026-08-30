import sys

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

migration_code = '''
		# Migrate users table for profile fields
		table_info = connection.execute("PRAGMA table_info(users)").fetchall()
		columns = [col['name'] for col in table_info]
		if 'email' not in columns:
			connection.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN phone_number TEXT DEFAULT ''")
			connection.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT DEFAULT ''")
'''

content = content.replace(
    'connection.execute("INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)",',
    migration_code + '\n\t\tconnection.execute("INSERT OR IGNORE INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)",'
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
