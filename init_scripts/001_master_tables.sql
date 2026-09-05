-- 001: Master (lookup) tables.
-- Used by Admin > Users, Admin > Masters, Profile, Groups and the
-- /api/v1/departments|positions|locations endpoints. Column names match the
-- queries in app.py exactly (department_id/department_name, location_id/..., id/name).

CREATE TABLE IF NOT EXISTS departments (
    department_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    department_name TEXT    NOT NULL UNIQUE,
    department_code TEXT    NOT NULL UNIQUE,
    description     TEXT    DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'Active',
    created_by      INTEGER REFERENCES users(id),
    updated_by      INTEGER REFERENCES users(id),
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS locations (
    location_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    location_name TEXT    NOT NULL UNIQUE,
    location_code TEXT    NOT NULL UNIQUE,
    city          TEXT    NOT NULL DEFAULT '',
    country       TEXT    NOT NULL DEFAULT '',
    address       TEXT    DEFAULT '',
    state         TEXT    DEFAULT '',
    postal_code   TEXT    DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'Active',
    created_by    INTEGER REFERENCES users(id),
    updated_by    INTEGER REFERENCES users(id),
    created_at    TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    status     TEXT    NOT NULL DEFAULT 'Active',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT    DEFAULT CURRENT_TIMESTAMP
);
