import pandas as pd
import sqlite3

df = pd.read_excel("Users/grade12.xlsx")

conn = sqlite3.connect("school.db")
cursor = conn.cursor()

for _, row in df.iterrows():
    username = str(row["username"]).strip().upper()
    full_name = str(row["full_name"]).strip()
    group_name = str(row["group"]).strip()

    cursor.execute("""
    INSERT INTO users (username, full_name, group_name, role)
    VALUES (?, ?, ?, 'student')
    ON CONFLICT(username) DO UPDATE SET
        full_name = excluded.full_name,
        group_name = excluded.group_name
    """, (username, full_name, group_name))

conn.commit()
conn.close()