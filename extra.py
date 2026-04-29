import sqlite3

conn = sqlite3.connect("school.db")
cursor = conn.cursor()

# Remove all login history so attendance can be retested from a clean state
cursor.execute("DELETE FROM login_history")
# Also remove manual overrides to avoid stale attendance state
cursor.execute("DELETE FROM attendance_override")

conn.commit()
conn.close()

print("Cleared login history and attendance overrides ✅")