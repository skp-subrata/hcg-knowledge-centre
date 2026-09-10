-- 012: Seed a real course on the Dell Boomi integration platform, with a 5-question
-- multiple-choice post-assessment. Runs exactly once per database (tracked in
-- schema_migrations like every other init script), so plain INSERTs are fine here --
-- no INSERT OR IGNORE needed, and the course/bank names below only need to be unique
-- enough to resolve unambiguously within this one script's own subqueries.

INSERT INTO courses (name, description, category, content_type, content_url, status, tags, duration_minutes, difficulty, thumbnail_color, created_by)
VALUES (
    'Boomi Integration Platform Fundamentals',
    'An introduction to Dell Boomi, a cloud-based Integration Platform as a Service (iPaaS) used to connect applications, data and systems across an organization. Covers the AtomSphere platform, its Atom/Molecule/Cloud runtime engines, the low-code Process Canvas for building integrations with little or no hand-written code, and common use cases including application and data integration, EDI/B2B trading-partner data exchange, and API management.',
    'Integration',
    'URL',
    'https://boomi.com/platform/integration/',
    'published',
    'boomi,integration,ipaas,api',
    45,
    'beginner',
    '#0071e3',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1)
);

INSERT INTO assessments (course_id, type, title, pass_percentage, max_attempts)
VALUES (
    (SELECT id FROM courses WHERE name = 'Boomi Integration Platform Fundamentals'),
    'post',
    'Boomi Integration Platform Fundamentals: Final Assessment',
    70,
    3
);

INSERT INTO question_banks (name, category, created_by)
VALUES (
    'Boomi Integration Platform Fundamentals Question Bank',
    'Integration',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1)
);

INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation)
VALUES (
    (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank'),
    'What type of platform is Dell Boomi primarily known as?',
    'A relational database management system',
    'An Integration Platform as a Service (iPaaS)',
    'A video conferencing tool',
    'A physical server appliance',
    'b',
    1,
    'easy',
    'boomi',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1),
    'Boomi is a cloud-based Integration Platform as a Service (iPaaS) used to connect applications, data and systems.'
);

INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation)
VALUES (
    (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank'),
    'What is the name of Boomi''s core integration platform?',
    'AtomSphere',
    'CloudConnect',
    'DataBridge',
    'FlowEngine',
    'a',
    1,
    'easy',
    'boomi',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1),
    'Boomi''s platform is called AtomSphere.'
);

INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation)
VALUES (
    (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank'),
    'Which of these is NOT one of Boomi''s runtime engine deployment options?',
    'Atom',
    'Molecule',
    'Cloud',
    'Nucleus',
    'd',
    1,
    'medium',
    'boomi',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1),
    'Boomi''s runtime engines are Atom (single node), Molecule (clustered) and the Boomi Cloud -- there is no "Nucleus" runtime.'
);

INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation)
VALUES (
    (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank'),
    'How does Boomi primarily let users build integrations, without heavy coding?',
    'A visual, low-code Process Canvas',
    'Hand-written SQL stored procedures only',
    'Editing raw XML configuration files by hand',
    'A command-line-only interface',
    'a',
    1,
    'easy',
    'boomi',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1),
    'Boomi provides a visual, drag-and-drop Process Canvas for building integrations with little or no code.'
);

INSERT INTO questions (question_bank_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, difficulty, topic_tag, created_by, explanation)
VALUES (
    (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank'),
    'Besides connecting applications and data, which of these is a common Boomi use case?',
    'EDI / B2B trading-partner data exchange',
    '3D game rendering',
    'Physical network cable installation',
    'Payroll tax filing',
    'a',
    1,
    'medium',
    'boomi',
    (SELECT id FROM users WHERE LOWER(role) = 'admin' ORDER BY id ASC LIMIT 1),
    'Boomi is also widely used for EDI and B2B integration (automating data exchange with trading partners) and for API management.'
);

INSERT INTO assessment_questions (assessment_id, question_id)
SELECT
    (SELECT id FROM assessments WHERE course_id = (SELECT id FROM courses WHERE name = 'Boomi Integration Platform Fundamentals') AND type = 'post'),
    q.id
FROM questions q
WHERE q.question_bank_id = (SELECT id FROM question_banks WHERE name = 'Boomi Integration Platform Fundamentals Question Bank');
