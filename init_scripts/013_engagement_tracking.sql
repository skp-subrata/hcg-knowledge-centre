-- 013: durable login tracking + IP capture for the System & activity engagement dashboard.
--
-- activity_log is pruned after 90 days (see log_activity() in app.py), which is fine for trend
-- charts but wrong for an all-time "total unique users" count -- that needs to survive pruning.
-- users.first_login_at/last_login_at are set once, on every successful login, independent of
-- the activity log's retention window.
--
-- ip_address on activity_log captures the request's client IP (best-effort; NULL when not
-- available, e.g. a background/non-request context) for every new row going forward -- existing
-- rows have no IP recorded, since this isn't retroactive.
ALTER TABLE users ADD COLUMN first_login_at TEXT;
ALTER TABLE users ADD COLUMN last_login_at TEXT;
ALTER TABLE activity_log ADD COLUMN ip_address TEXT;

-- Backfill from whatever login_success history activity_log already has (up to 90 days) so the
-- "all-time unique users" KPI isn't wrongly stuck at 0 for everyone right after this ships.
-- Anyone whose last login predates that window still shows as "never" until they next log in --
-- an accepted gap, since that history no longer exists anywhere to recover it from.
UPDATE users SET last_login_at = (
    SELECT MAX(created_at) FROM activity_log WHERE activity_log.user_id = users.id AND event_type = 'login_success'
) WHERE EXISTS (SELECT 1 FROM activity_log WHERE activity_log.user_id = users.id AND event_type = 'login_success');

UPDATE users SET first_login_at = (
    SELECT MIN(created_at) FROM activity_log WHERE activity_log.user_id = users.id AND event_type = 'login_success'
) WHERE EXISTS (SELECT 1 FROM activity_log WHERE activity_log.user_id = users.id AND event_type = 'login_success');
