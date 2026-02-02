
from infrastructure.database import Database
from infrastructure.indexer import Indexer
import os
import time

def main():
    print("Testing Indexer...")
    db = Database("test_debug.db")
    indexer = Indexer(db)
    
    test_dir = os.path.join(os.getcwd(), "TestFiles")
    print(f"Indexing directory: {test_dir}")
    
    def progress(msg):
        print(f"PROGRESS: {msg}")
        
    def complete(count):
        print(f"COMPLETED: {count} projects indexés.")

    indexer._index_worker(test_dir, progress, complete)
    
    # Check DB
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM projects")
    count = cursor.fetchone()[0]
    print(f"Final project count in DB: {count}")
    conn.close()

if __name__ == "__main__":
    main()
