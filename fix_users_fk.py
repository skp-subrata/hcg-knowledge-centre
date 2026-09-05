import sqlite3

db = sqlite3.connect('d:/apps/users.db')
db.execute("PRAGMA foreign_keys = OFF")

# Get old table schema
old_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
print("Old SQL:", old_sql)

# Create new table
new_sql = '''
CREATE TABLE users_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'moderator', 'basic user')),
    email TEXT DEFAULT '',
    phone_number TEXT DEFAULT '',
    profile_picture TEXT DEFAULT '',
    employee_id TEXT DEFAULT '',
    department TEXT DEFAULT '',
    location TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    department_id INTEGER REFERENCES departments(department_id),
    position_id INTEGER REFERENCES positions(id),
    about_me TEXT DEFAULT '',
    location_id INTEGER REFERENCES locations(location_id)
)
'''
db.execute(new_sql)

# Copy data
columns = "id, full_name, username, password_hash, role, email, phone_number, profile_picture, employee_id, department, location, is_active, created_at, updated_at, department_id, position_id, about_me, location_id"
db.execute(f"INSERT INTO users_new ({columns}) SELECT {columns} FROM users")

# Drop old and rename new
db.execute("DROP TABLE users")
db.execute("ALTER TABLE users_new RENAME TO users")

db.commit()
print("Successfully recreated users table with correct foreign keys.")
