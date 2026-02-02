import sqlite3
import datetime
from typing import List, Dict, Optional
import os

class Database:
    def __init__(self, db_path: str = "mwquote_index.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """Initialize the database schema."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Projects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                reference TEXT,
                client TEXT,
                filepath TEXT UNIQUE,
                drawing_filename TEXT,
                last_modified TIMESTAMP,
                status TEXT DEFAULT 'En construction',
                min_qty INTEGER,
                max_qty INTEGER,
                date_construction TEXT,
                date_finalisee TEXT,
                date_transmise TEXT
            )
        ''')

        # Migration for existing DBs: Add new columns if they don't exist
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN status TEXT DEFAULT 'En construction'")
        except: pass
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN min_qty INTEGER")
        except: pass
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN max_qty INTEGER")
        except: pass
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN date_construction TEXT")
        except: pass
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN date_finalisee TEXT")
        except: pass
        try:
            cursor.execute("ALTER TABLE projects ADD COLUMN date_transmise TEXT")
        except: pass

        # Tags table (many-to-one with projects)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                tag TEXT,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        conn.close()

    def upsert_project(self, project_data: Dict) -> int:
        """Insert or update a project."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if project exists by filepath
            cursor.execute('SELECT id FROM projects WHERE filepath = ?', (project_data['filepath'],))
            row = cursor.fetchone()
            
            if row:
                project_id = row[0]
                cursor.execute('''
                    UPDATE projects 
                    SET name = ?, reference = ?, client = ?, drawing_filename = ?, 
                        last_modified = ?, status = ?, min_qty = ?, max_qty = ?,
                        date_construction = ?, date_finalisee = ?, date_transmise = ?
                    WHERE id = ?
                ''', (
                    project_data['name'], 
                    project_data['reference'], 
                    project_data['client'], 
                    project_data['drawing_filename'],
                    datetime.datetime.now(),
                    project_data.get('status', 'En construction'),
                    project_data.get('min_qty'),
                    project_data.get('max_qty'),
                    project_data.get('date_construction'),
                    project_data.get('date_finalisee'),
                    project_data.get('date_transmise'),
                    project_id
                ))
                # Clear existing tags to re-insert
                cursor.execute('DELETE FROM tags WHERE project_id = ?', (project_id,))
            else:
                cursor.execute('''
                    INSERT INTO projects (name, reference, client, filepath, drawing_filename, last_modified, 
                                        status, min_qty, max_qty, date_construction, date_finalisee, date_transmise)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    project_data['name'], 
                    project_data['reference'], 
                    project_data['client'], 
                    project_data['filepath'], 
                    project_data['drawing_filename'],
                    datetime.datetime.now(),
                    project_data.get('status', 'En construction'),
                    project_data.get('min_qty'),
                    project_data.get('max_qty'),
                    project_data.get('date_construction'),
                    project_data.get('date_finalisee'),
                    project_data.get('date_transmise')
                ))
                project_id = cursor.lastrowid
                
            # Insert tags
            for tag in project_data.get('tags', []):
                if tag:
                    cursor.execute('INSERT INTO tags (project_id, tag) VALUES (?, ?)', (project_id, tag))
            
            return project_id

    def search_projects(self, 
                       reference: str = None, 
                       client: str = None, 
                       tag: str = None) -> List[Dict]:
        """Search for projects matching criteria."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT DISTINCT p.* FROM projects p"
            joins = []
            where_clauses = []
            params = []
            
            if tag and tag.strip():
                joins.append("JOIN tags t ON p.id = t.project_id")
                where_clauses.append("t.tag LIKE ?")
                params.append(f"%{tag.strip()}%")
                
            if reference and reference.strip():
                where_clauses.append("p.reference LIKE ?")
                params.append(f"%{reference.strip()}%")
                
            if client and client.strip():
                where_clauses.append("p.client LIKE ?")
                params.append(f"%{client.strip()}%")
                
            full_query = query
            if joins:
                full_query += " " + " ".join(joins)
            if where_clauses:
                full_query += " WHERE " + " AND ".join(where_clauses)
                
            full_query += " ORDER BY p.last_modified DESC"
            
            cursor.execute(full_query, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                p = dict(row)
                # Fetch tags for each project
                cursor.execute('SELECT tag FROM tags WHERE project_id = ?', (p['id'],))
                tags = [t['tag'] for t in cursor.fetchall()]
                p['tags'] = tags
                results.append(p)
                
            return results

    def delete_project(self, project_id: int):
        """Delete a project and its associated tags."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Fkeys are not active by default in SQLite unless explicitly enabled, 
            # so we delete tags manually to be sure if ON DELETE CASCADE isn't enough.
            cursor.execute('DELETE FROM tags WHERE project_id = ?', (project_id,))
            cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
            conn.commit()

    def get_all_clients(self) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT client FROM projects ORDER BY client")
        clients = [row[0] for row in cursor.fetchall() if row[0]]
        conn.close()
        return clients

    def get_db_path(self) -> str:
        return os.path.abspath(self.db_path)

    def check_integrity(self) -> bool:
        """Run a SQLite integrity check."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            return result == "ok"

    def clear_all(self):
        """Wipe all data from the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tags")
            cursor.execute("DELETE FROM projects")
            # VACUUM cannot be run inside a transaction
        
        # Open separate connection without transaction for VACUUM
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("VACUUM")
        conn.close()

    def get_stats(self) -> Dict:
        """Get database statistics."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM projects")
            stats['total_projects'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT client) FROM projects")
            stats['total_clients'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tags")
            stats['total_tags_links'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT tag) FROM tags")
            stats['unique_tags'] = cursor.fetchone()[0]
            
            if os.path.exists(self.db_path):
                stats['db_size_kb'] = os.path.getsize(self.db_path) / 1024
            else:
                stats['db_size_kb'] = 0
                
        return stats

    def delete_missing_files(self):
        """Remove projects from DB that no longer exist on disk."""
        removed = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filepath FROM projects")
            rows = cursor.fetchall()
            for pid, path in rows:
                if not os.path.exists(path):
                    cursor.execute("DELETE FROM projects WHERE id = ?", (pid,))
                    removed += 1
            conn.commit()
        return removed
