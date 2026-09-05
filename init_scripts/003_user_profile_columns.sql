-- 003: Profile columns on users that point at the master tables.
-- SQLite has no "ADD COLUMN IF NOT EXISTS"; db_init.py skips an ADD COLUMN whose
-- column already exists, so this script is safe on databases that predate it.

ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES departments(department_id);
ALTER TABLE users ADD COLUMN position_id   INTEGER REFERENCES positions(id);
ALTER TABLE users ADD COLUMN location_id   INTEGER REFERENCES locations(location_id);
ALTER TABLE users ADD COLUMN about_me      TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id);
CREATE INDEX IF NOT EXISTS idx_users_location   ON users(location_id);
