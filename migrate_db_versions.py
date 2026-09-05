from app import get_db
import json

with get_db() as connection:
    connection.execute("""
    CREATE TABLE IF NOT EXISTS app_releases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_number TEXT UNIQUE NOT NULL,
        release_title TEXT NOT NULL,
        release_date TEXT DEFAULT CURRENT_TIMESTAMP,
        features TEXT,
        improvements TEXT,
        bug_fixes TEXT,
        is_active INTEGER DEFAULT 0
    )
    """)
    
    release_count = connection.execute("SELECT COUNT(*) FROM app_releases").fetchone()[0]
    if release_count == 0:
        connection.execute('''
            INSERT INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (
            '1.5.0', 
            '1.5.0 Release', 
            json.dumps(["Interactive Profile Customization with Interest Chips", "Dynamic Release Notes Engine"]),
            json.dumps(["Streamlined Add User Admin Workflow", "Restored Edit User Popup Wizard", "Added Employee ID to Tables"]),
            json.dumps(["Fixed template syntax error on Admin panel"])
        ))
        
        connection.execute('''
            INSERT INTO app_releases (version_number, release_title, features, improvements, bug_fixes, is_active)
            VALUES (?, ?, ?, ?, ?, 0)
        ''', (
            '1.4.0', 
            '1.4.0 Release', 
            json.dumps([]),
            json.dumps([]),
            json.dumps([])
        ))
print("Database migrated successfully.")
