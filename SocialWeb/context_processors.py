from __future__ import annotations
from typing import Dict

def notifications(request) -> Dict[str, object]:
    """Expose unread notifications info to all templates.
    Returns:
      - notifications_unread_count: int
      - has_unread_notifications: bool
    Safe to use even if Neo4j is down (wrapped in try/except).
    """
    count = 0
    try:
        username = request.session.get('username')
        if username:
            # Import inside to avoid potential import-time issues
            from .models import Notification
            try:
                # neomodel query; wrap in list to count safely
                count = len(list(Notification.nodes.filter(to_username=username, seen=False)))
            except Exception:
                count = 0
    except Exception:
        count = 0
    return {
        'notifications_unread_count': count,
        'has_unread_notifications': bool(count > 0),
    }
