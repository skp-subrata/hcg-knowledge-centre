-- 010: Compulsory courses.
-- Ported from origin/master alongside 009's system-generated groups. A compulsory,
-- published course is auto-assigned to every active user (via assign_compulsory_course_to_all
-- in app.py) and to every newly onboarded/resynced user (via assign_compulsory_courses_to_user,
-- called from sync_user_groups).

ALTER TABLE courses ADD COLUMN is_compulsory INTEGER DEFAULT 0;
