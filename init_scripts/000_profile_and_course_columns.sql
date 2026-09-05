-- 000: Columns that seed_demo_data() used to add on the fly.
-- They live here so the schema is complete even when demo seeding is disabled
-- (LMS_SEED_DEMO=0). db_init.py skips an ADD COLUMN whose column already exists.

ALTER TABLE users   ADD COLUMN email           TEXT    DEFAULT '';
ALTER TABLE users   ADD COLUMN phone_number    TEXT    DEFAULT '';
ALTER TABLE users   ADD COLUMN profile_picture TEXT    DEFAULT '';

ALTER TABLE courses ADD COLUMN tags             TEXT    DEFAULT '';
ALTER TABLE courses ADD COLUMN duration_minutes INTEGER DEFAULT 0;
ALTER TABLE courses ADD COLUMN difficulty       TEXT    DEFAULT 'beginner';
ALTER TABLE courses ADD COLUMN thumbnail_color  TEXT    DEFAULT '#6366f1';
