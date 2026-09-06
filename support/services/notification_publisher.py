"""
Decoupled Notification Publisher.
Publishes support event notifications through clean interface points.
Safe fallback if main app notification mechanism is unavailable.
"""


def publish_support_event(connection, event_type, recipient_user_id, message, target_url=None):
    """
    Publish a support event notification.
    If the primary app notifications table exists, inserts a notification record safely.
    """
    if not recipient_user_id:
        return False

    try:
        # Check if notifications table exists in the database
        has_notif_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notifications'"
        ).fetchone()

        if has_notif_table:
            connection.execute(
                """INSERT INTO notifications (user_id, message, type, is_read, target_url, created_at)
                   VALUES (?, ?, ?, 0, ?, CURRENT_TIMESTAMP)""",
                (recipient_user_id, message, f"SUPPORT_{event_type}", target_url or "/support")
            )
            return True
    except Exception as e:
        # Log error safely without crashing support module operations
        print(f"[SupportNotificationPublisher] Notice: Notification publish failed ({e})")

    return False

