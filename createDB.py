import os
import sqlite3
# =========================================================
# FOLDERS
# =========================================================
DB_FOLDER = "databases"
HISTORY_FOLDER = "sql_history"

os.makedirs(DB_FOLDER, exist_ok=True)
os.makedirs(HISTORY_FOLDER, exist_ok=True)

HISTORY_FILE = os.path.join(
    HISTORY_FOLDER,
    "history.json"
)
# =========================================================
# CREATE DEFAULT DATABASE
# =========================================================
default_db = os.path.join(
    DB_FOLDER,
    "names.db"
)

if not os.path.exists(default_db):

    conn = sqlite3.connect(default_db)

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        age INTEGER
    )
    """)

    sample_data = [
        ("Akshay", "akshay@test.com", 25),
        ("Rahul", "rahul@test.com", 30),
        ("Akshay", "akshay@test.com", 25),
        ("Priya", None, 22)
    ]

    cursor.executemany("""
    INSERT INTO users (
        name,
        email,
        age
    )
    VALUES (?, ?, ?)
    """, sample_data)

    conn.commit()
    conn.close()
