-- 008: system health snapshots and a bounded activity log.
--
-- system_metric_snapshots is written only when an admin opens the System health page (there
-- is no background sampler) -- see app.py's record_system_snapshot(). History is therefore
-- sparse by design, filling in over time as the page gets checked.
--
-- activity_log captures logins/logouts, page views (real navigations only -- see the
-- after_request hook in app.py, which excludes /api/*, /static/* and anything that isn't an
-- HTML response), and a small, deliberately bounded set of business events (post reviewed,
-- assessment submitted, course certified). It is not a full request log. Rows older than 90
-- days are pruned automatically by log_activity() so it can't grow without bound against the
-- disk quota.

CREATE TABLE IF NOT EXISTS system_metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    cpu_used_seconds REAL,
    cpu_limit_seconds REAL,
    disk_used_bytes INTEGER,
    disk_quota_bytes INTEGER,
    worker_memory_bytes INTEGER,
    db_size_bytes INTEGER,
    healthy INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_recorded_at ON system_metric_snapshots(recorded_at);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_user_id ON activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_event_type ON activity_log(event_type);
