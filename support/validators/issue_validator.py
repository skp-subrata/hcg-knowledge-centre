"""
Issue Payload & Status Transition Validator.
"""


def validate_create_issue_payload(title, description, category_id):
    """
    Validate mandatory fields for creating a support issue.
    """
    errors = []
    if not title or not title.strip():
        errors.append("Issue Title is required.")
    elif len(title.strip()) < 5:
        errors.append("Issue Title must be at least 5 characters long.")

    if not description or not description.strip():
        errors.append("Issue Description is required.")
    elif len(description.strip()) < 10:
        errors.append("Issue Description must be at least 10 characters long.")

    if not category_id:
        errors.append("Issue Category is required.")

    return len(errors) == 0, errors

