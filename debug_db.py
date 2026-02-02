import sqlite3
import os

db_path = "mwquote_index.db"
if not os.path.exists(db_path):
    print(f"Database file {db_path} not found.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("--- Projects ---")
    try:
        cursor.execute("SELECT COUNT(*) FROM projects")
        print(f"Count: {cursor.fetchone()[0]}")
        cursor.execute("SELECT id, name, reference, client, filepath FROM projects LIMIT 5")
        for row in cursor.fetchall():
            print(row)
    except Exception as e:
        print(f"Error reading projects: {e}")
        
    print("\n--- Tags ---")
    try:
        cursor.execute("SELECT COUNT(*) FROM tags")
        print(f"Count: {cursor.fetchone()[0]}")
        cursor.execute("SELECT * FROM tags LIMIT 5")
        for row in cursor.fetchall():
            print(row)
    except Exception as e:
        print(f"Error reading tags: {e}")

    conn.close()
