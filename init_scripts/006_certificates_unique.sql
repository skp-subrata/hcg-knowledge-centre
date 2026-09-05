-- 006: One certificate per (student, course).
-- Earlier versions generated a fresh cert_uid on every feedback submission, so a learner
-- could end up with several certificate rows for one course. Keep the earliest row, then
-- enforce uniqueness so both the web and API paths reuse it.

DELETE FROM certificates
WHERE id NOT IN (SELECT MIN(id) FROM certificates GROUP BY student_id, course_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_certificates_student_course ON certificates(student_id, course_id);
