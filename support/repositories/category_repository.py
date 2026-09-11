"""
Category Repository.
Data access layer for support_categories.
"""


def get_all_categories(connection, active_only=True):
    """Fetch categories from DB."""
    sql = "SELECT * FROM support_categories"
    if active_only:
        sql += " WHERE status = 'Active'"
    sql += " ORDER BY name ASC"
    return connection.execute(sql).fetchall()


def get_category_by_id(connection, category_id):
    """Fetch a single category by ID."""
    return connection.execute(
        "SELECT * FROM support_categories WHERE id = ?", (category_id,)
    ).fetchone()


def get_category_by_code(connection, code):
    """Fetch a single category by its stable code (e.g. used to resolve the feedback
    widget's compact "type" into a real category without hardcoding an id)."""
    return connection.execute(
        "SELECT * FROM support_categories WHERE code = ?", (code,)
    ).fetchone()


def create_category(connection, name, code, description=""):
    """Create a new category master record."""
    cursor = connection.execute(
        "INSERT INTO support_categories (name, code, description) VALUES (?, ?, ?)",
        (name.strip(), code.strip().upper(), description.strip())
    )
    return cursor.lastrowid


def update_category(connection, category_id, name, code, description="", status="Active"):
    """Update existing category master record."""
    connection.execute(
        """UPDATE support_categories
           SET name = ?, code = ?, description = ?, status = ?
           WHERE id = ?""",
        (name.strip(), code.strip().upper(), description.strip(), status, category_id)
    )

