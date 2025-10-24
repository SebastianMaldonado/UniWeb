from __future__ import annotations
from typing import Dict

def notifications(request) -> Dict[str, object]:
    """Expose unread notifications info to all templates.
    Returns:
      - notifications_unread_count: int
      - has_unread_notifications: bool
    Safe to use even if Neo4j is down (wrapped in try/except).
    """
    notif_count = 0
    msg_count = 0
    try:
        username = request.session.get('username')
        if username:
            # Import inside to avoid potential import-time issues
            from .models import Notification, Message
            try:
                # neomodel query; wrap in list to count safely
                notif_count = len(list(Notification.nodes.filter(to_username=username, seen=False)))
            except Exception:
                notif_count = 0
            try:
                msg_count = len(list(Message.nodes.filter(receiver_username=username, seen=False)))
            except Exception:
                msg_count = 0
    except Exception:
        notif_count = 0
        msg_count = 0
    return {
        'notifications_unread_count': notif_count,
        'has_unread_notifications': bool(notif_count > 0),
        'messages_unread_count': msg_count,
        'has_unread_messages': bool(msg_count > 0),
    }
