import threading
import time
from datetime import datetime, timedelta

TIMEOUT = 60
active_users = {}
lock = threading.Lock()


def update_active_user(username):
    """Update the last seen time for a user in the active_users dict."""
    with lock:
        active_users[username] = datetime.now()


def cleanup_thread():
    while True:
        now = datetime.now()
        with lock:
            to_remove = []
            for user, last_seen in list(active_users.items()):
                if now - last_seen > timedelta(seconds=TIMEOUT):
                    to_remove.append(user)
            for user in to_remove:
                del active_users[user]
        time.sleep(30)
