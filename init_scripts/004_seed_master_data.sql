-- 004: Starter master data so the dropdowns work on a fresh install.
-- Adding a user (Admin) and saving a profile both require a location, so at
-- least one must exist. INSERT OR IGNORE keeps re-runs and existing rows safe.

INSERT OR IGNORE INTO departments (department_name, department_code, description) VALUES
    ('Operations',      'OPS', 'Operations and delivery'),
    ('Engineering',     'ENG', 'Product and platform engineering'),
    ('Human Resources', 'HR',  'People, learning and development'),
    ('Sales',           'SAL', 'Sales and account management'),
    ('Finance',         'FIN', 'Finance and accounting');

INSERT OR IGNORE INTO locations (location_name, location_code, city, country, state) VALUES
    ('Hyderabad', 'HYD', 'Hyderabad', 'India', 'Telangana'),
    ('Bengaluru', 'BLR', 'Bengaluru', 'India', 'Karnataka'),
    ('Mumbai',    'BOM', 'Mumbai',    'India', 'Maharashtra'),
    ('Remote',    'RMT', 'Remote',    'India', '');

INSERT OR IGNORE INTO positions (name) VALUES
    ('Analyst'), ('Senior Analyst'), ('Team Lead'), ('Manager'), ('Director');

INSERT OR IGNORE INTO interest_master (interest_name, normalized_name) VALUES
    ('Python',          'python'),
    ('Data Analytics',  'data analytics'),
    ('Leadership',      'leadership'),
    ('Cloud Computing', 'cloud computing'),
    ('Design',          'design'),
    ('Communication',   'communication');
