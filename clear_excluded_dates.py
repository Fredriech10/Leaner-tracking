import sqlite3

DB_NAME = "school.db"

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

cursor.execute("DELETE FROM excluded_dates")
conn.commit()

print(f"Cleared all excluded dates. Rows deleted: {cursor.rowcount}")

conn.close()
