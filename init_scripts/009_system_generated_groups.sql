-- 009: System-generated groups (Department / Location / All Users).
-- Ported from origin/master's compulsory-courses-and-groups commit. Membership in these
-- groups is computed automatically (see sync_department_group / sync_location_group /
-- sync_all_users_group / sync_user_groups / ensure_system_generated_groups in app.py) rather
-- than maintained by hand; manual add/remove is blocked on them in the groups routes.

ALTER TABLE groups ADD COLUMN system_generated INTEGER DEFAULT 0;
ALTER TABLE groups ADD COLUMN source_master_type TEXT DEFAULT '';
ALTER TABLE groups ADD COLUMN source_master_id INTEGER DEFAULT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_system_source
    ON groups(group_type, source_master_type, source_master_id) WHERE system_generated = 1;
