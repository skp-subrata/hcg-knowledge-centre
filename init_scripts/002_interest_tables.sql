-- 002: Interests master and the user <-> interest link table.
-- Used by Admin > Users, Admin > Masters, Profile (interest chips) and
-- /api/interests, /api/users/<id>/interests.

CREATE TABLE IF NOT EXISTS interest_master (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    interest_name   TEXT    NOT NULL,
    normalized_name TEXT    NOT NULL UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'Active',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_interest (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interest_master(id) ON DELETE CASCADE,
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, interest_id)
);

CREATE INDEX IF NOT EXISTS idx_user_interest_user     ON user_interest(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interest_interest ON user_interest(interest_id);
