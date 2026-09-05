import sqlite3

db = sqlite3.connect('d:/apps/users.db')
db.execute("PRAGMA foreign_keys = OFF")

# 1. Create interest_master
db.execute('''
CREATE TABLE interest_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interest_name TEXT NOT NULL,
    normalized_name TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'Active',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
''')

# Migrate data from interests to interest_master
# We assume interests has id, name, status, created_at, created_by
# We'll normalize the name by lowercasing and stripping whitespace
rows = db.execute("SELECT id, name, status, created_at, created_by FROM interests").fetchall()
for row in rows:
    i_id, name, status, created_at, created_by = row
    normalized = " ".join(name.strip().lower().split())
    try:
        db.execute('''
            INSERT INTO interest_master (id, interest_name, normalized_name, status, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (i_id, name, normalized, status.capitalize(), created_by, created_at))
    except sqlite3.IntegrityError:
        # If there's already a duplicate normalized name, we skip it
        # and we need to map the old ID to the new one in user_interest, but for now we skip
        pass

# 2. Create user_interest
db.execute('''
CREATE TABLE user_interest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interest_master(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, interest_id)
)
''')

# Migrate data from user_interests to user_interest
db.execute('''
INSERT INTO user_interest (user_id, interest_id, created_at)
SELECT user_id, interest_id, created_at FROM user_interests
''')

# 3. Drop old tables
db.execute("DROP TABLE user_interests")
db.execute("DROP TABLE interests")

db.commit()
print("Migration completed successfully.")
