import sqlite3
import datetime
from typing import List, Dict, Optional
import os

class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
            db_dir = os.path.join(app_data, "MWQuote")
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "mwquote_index.db")
        
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
                date_transmise TEXT,
                content_hash TEXT,
                is_missing INTEGER DEFAULT 0,
                devis_refs TEXT,
                mwq_uuid TEXT
            )
        ''')

        # Migration for existing DBs: Add new columns if they don't exist
        migrations = [
            "ALTER TABLE projects ADD COLUMN status TEXT DEFAULT 'En construction'",
            "ALTER TABLE projects ADD COLUMN min_qty INTEGER",
            "ALTER TABLE projects ADD COLUMN max_qty INTEGER",
            "ALTER TABLE projects ADD COLUMN date_construction TEXT",
            "ALTER TABLE projects ADD COLUMN date_finalisee TEXT",
            "ALTER TABLE projects ADD COLUMN date_transmise TEXT",
            "ALTER TABLE projects ADD COLUMN content_hash TEXT",
            "ALTER TABLE projects ADD COLUMN is_missing INTEGER DEFAULT 0",
            "ALTER TABLE projects ADD COLUMN devis_refs TEXT",
            "ALTER TABLE projects ADD COLUMN mwq_uuid TEXT",
        ]
        for migration in migrations:
            try:
                cursor.execute(migration)
            except:
                pass

        # Create index on content_hash for fast reconnection lookups
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON projects(content_hash)")
        except:
            pass

        # Create index on mwq_uuid for fast UUID lookups
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mwq_uuid ON projects(mwq_uuid)")
        except:
            pass

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

    def init_quote_numbering_table(self):
        """Initialize quote numbering table for persistent counters."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quote_numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'OD',
                counter INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, prefix)
            )
        ''')
        
        # Create index for fast lookups
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_quote_date_prefix ON quote_numbers(date, prefix)")
        except:
            pass
        
        conn.commit()
        conn.close()

    def upsert_project(self, project_data: Dict) -> int:
        """Insert or update a project."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            content_hash = project_data.get('content_hash')
            filepath = project_data['filepath']

            # First, check if project exists by filepath
            cursor.execute('SELECT id FROM projects WHERE filepath = ?', (filepath,))
            row = cursor.fetchone()

            # If not found by path but we have a hash, try to find by hash (reconnection)
            if not row and content_hash:
                cursor.execute('SELECT id, filepath FROM projects WHERE content_hash = ? AND is_missing = 1', (content_hash,))
                hash_row = cursor.fetchone()
                if hash_row:
                    # Found a missing project with same hash - reconnect it!
                    project_id = hash_row[0]
                    old_path = hash_row[1]
                    print(f"Reconnecting project: {old_path} -> {filepath}")
                    cursor.execute('''
                        UPDATE projects
                        SET filepath = ?, is_missing = 0, name = ?, reference = ?, client = ?,
                            drawing_filename = ?, last_modified = ?, status = ?, min_qty = ?, max_qty = ?,
                            date_construction = ?, date_finalisee = ?, date_transmise = ?, content_hash = ?,
                        devis_refs = ?
                    WHERE id = ?
                ''', (
                    filepath,
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
                    content_hash,
                    ", ".join([f"{e['devis_ref']} ({e['date']})" for e in project_data.get('export_history', [])]),
                    project_id
                ))
                    # Clear existing tags and re-insert
                    cursor.execute('DELETE FROM tags WHERE project_id = ?', (project_id,))
                    for tag in project_data.get('tags', []):
                        if tag:
                            cursor.execute('INSERT INTO tags (project_id, tag) VALUES (?, ?)', (project_id, tag))
                    return project_id

            if row:
                project_id = row[0]
                cursor.execute('''
                    UPDATE projects
                    SET name = ?, reference = ?, client = ?, drawing_filename = ?,
                        last_modified = ?, status = ?, min_qty = ?, max_qty = ?,
                        date_construction = ?, date_finalisee = ?, date_transmise = ?,
                        content_hash = ?, is_missing = 0, devis_refs = ?
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
                    content_hash,
                    ", ".join([f"{e['devis_ref']} ({e['date']})" for e in project_data.get('export_history', [])]),
                    project_id
                ))
                # Clear existing tags to re-insert
                cursor.execute('DELETE FROM tags WHERE project_id = ?', (project_id,))
            else:
                cursor.execute('''
                    INSERT INTO projects (name, reference, client, filepath, drawing_filename, last_modified,
                                        status, min_qty, max_qty, date_construction, date_finalisee, date_transmise,
                    content_hash, is_missing, devis_refs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (
                project_data['name'],
                project_data['reference'],
                project_data['client'],
                filepath,
                project_data['drawing_filename'],
                datetime.datetime.now(),
                project_data.get('status', 'En construction'),
                project_data.get('min_qty'),
                project_data.get('max_qty'),
                project_data.get('date_construction'),
                project_data.get('date_finalisee'),
                project_data.get('date_transmise'),
                content_hash,
                ", ".join([f"{e['devis_ref']} ({e['date']})" for e in project_data.get('export_history', [])])
            ))
                project_id = cursor.lastrowid

            # Insert tags
            for tag in project_data.get('tags', []):
                if tag:
                    cursor.execute('INSERT INTO tags (project_id, tag) VALUES (?, ?)', (project_id, tag))

            return project_id

    def search_projects(self,
                       global_search: str = None,
                       status: str = None,
                       sort_by: str = "last_modified",
                       sort_order: str = "DESC",
                       include_missing: bool = False) -> List[Dict]:
        """Search for projects matching criteria using a unified search term."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT DISTINCT p.* FROM projects p"
            joins = []
            where_clauses = []
            params = []

            # By default, exclude missing files
            if not include_missing:
                where_clauses.append("p.is_missing = 0")

            if global_search and global_search.strip():
                raw_term = global_search.strip()
                # Support '*' as wildcard by replacing it with SQL '%'
                if '*' in raw_term:
                    term = raw_term.replace('*', '%')
                else:
                    # Default to 'contains' search if no wildcard provided
                    term = f"%{raw_term}%"
                
                joins.append("LEFT JOIN tags t ON p.id = t.project_id")
                # Unified OR search across multiple fields
                search_clause = "(p.reference LIKE ? OR p.client LIKE ? OR p.devis_refs LIKE ? OR t.tag LIKE ?)"
                where_clauses.append(search_clause)
                params.extend([term, term, term, term])

            if status and status.strip() and status.lower() != "tous":
                where_clauses.append("p.status = ?")
                params.append(status.strip())

            full_query = query
            if joins:
                full_query += " " + " ".join(joins)
            if where_clauses:
                full_query += " WHERE " + " AND ".join(where_clauses)

            # Mapping for sorting columns to DB columns
            col_map = {
                "Référence": "reference",
                "Client": "client",
                "Status": "status",
                "Q. Min": "min_qty",
                "Q. Max": "max_qty",
                "Date Proj.": "project_date",
                "Devis": "devis_refs",
                "Tags": "tags",
                "Modifié le": "last_modified",
                "reference": "reference",
                "client": "client",
                "status": "status",
                "min_qty": "min_qty",
                "max_qty": "max_qty",
                "project_date": "project_date",
                "last_modified": "last_modified"
            }
            db_sort_col = col_map.get(sort_by, "last_modified")
            
            # Ensure sort_order is safe
            order = "DESC" if sort_order.upper() == "DESC" else "ASC"
            
            full_query += f" ORDER BY p.{db_sort_col} {order}"

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

    def find_by_hash(self, content_hash: str) -> Optional[Dict]:
        """Find a project by its content hash."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM projects WHERE content_hash = ?', (content_hash,))
            row = cursor.fetchone()
            if row:
                p = dict(row)
                cursor.execute('SELECT tag FROM tags WHERE project_id = ?', (p['id'],))
                p['tags'] = [t['tag'] for t in cursor.fetchall()]
                return p
            return None

    def mark_missing(self, filepath: str) -> bool:
        """Mark a project as missing (file not found)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE projects SET is_missing = 1 WHERE filepath = ?', (filepath,))
            return cursor.rowcount > 0

    def update_filepath(self, project_id_or_path, new_path: str):
        """Update the filepath for a project. 
        
        Can accept either:
        - project_id (int) to update by ID
        - old_path (str) to update by old path
        
        This replaces the old update_filepath(id, path) method for backward compatibility.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if isinstance(project_id_or_path, int):
                # Update by ID
                cursor.execute("UPDATE projects SET filepath = ?, is_missing = 0, last_modified = ? WHERE id = ?",
                             (new_path, datetime.datetime.now(), project_id_or_path))
            else:
                # Update by old path
                cursor.execute("UPDATE projects SET filepath = ?, is_missing = 0, last_modified = ? WHERE filepath = ?",
                             (new_path, datetime.datetime.now(), project_id_or_path))
            conn.commit()

    def get_missing_projects(self) -> List[Dict]:
        """Get all projects marked as missing."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM projects WHERE is_missing = 1')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def delete_project(self, project_id: int):
        """Delete a project and its associated tags."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tags WHERE project_id = ?', (project_id,))
            cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
            conn.commit()

    def get_all_clients(self) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT client FROM projects WHERE is_missing = 0 ORDER BY client")
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

        # Open separate connection without transaction for VACUUM
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("VACUUM")
        conn.close()

    def get_stats(self) -> Dict:
        """Get database statistics."""
        stats = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM projects WHERE is_missing = 0")
            stats['total_projects'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM projects WHERE is_missing = 1")
            stats['missing_projects'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT client) FROM projects WHERE is_missing = 0")
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

    def mark_missing_files(self) -> int:
        """Mark projects as missing if their files no longer exist on disk.

        Returns count of newly marked missing projects.
        """
        marked = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filepath FROM projects WHERE is_missing = 0")
            rows = cursor.fetchall()
            for pid, path in rows:
                if not os.path.exists(path):
                    cursor.execute("UPDATE projects SET is_missing = 1 WHERE id = ?", (pid,))
                    marked += 1
            conn.commit()
        return marked

    def delete_missing_files(self) -> int:
        """Remove projects from DB that are marked as missing (permanently)."""
        removed = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM projects WHERE is_missing = 1")
            rows = cursor.fetchall()
            for (pid,) in rows:
                cursor.execute("DELETE FROM tags WHERE project_id = ?", (pid,))
                cursor.execute("DELETE FROM projects WHERE id = ?", (pid,))
                removed += 1
            conn.commit()
        return removed

    def reconcile_files(self) -> Dict:
        """Check all file paths and update missing status.

        Returns stats about what was found.
        """
        stats = {'checked': 0, 'missing': 0, 'found': 0}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filepath, is_missing FROM projects")
            rows = cursor.fetchall()
            for pid, path, was_missing in rows:
                stats['checked'] += 1
                exists = os.path.exists(path)
                if exists and was_missing:
                    # File found again!
                    cursor.execute("UPDATE projects SET is_missing = 0 WHERE id = ?", (pid,))
                    stats['found'] += 1
                elif not exists and not was_missing:
                    # File went missing
                    cursor.execute("UPDATE projects SET is_missing = 1 WHERE id = ?", (pid,))
                    stats['missing'] += 1
            conn.commit()
        return stats

    def get_project_by_uuid(self, mwq_uuid: str):
        """Get project by its MWQ UUID."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE mwq_uuid = ?", (mwq_uuid,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_project_uuid(self, project_id: int, mwq_uuid: str):
        """Set the MWQ UUID for a project."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE projects SET mwq_uuid = ? WHERE id = ?", (mwq_uuid, project_id))
            conn.commit()

    def update_filepath_by_filepath(self, old_path: str, new_path: str):
        """Update filepath from old to new path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE projects SET filepath = ?, last_modified = ? WHERE filepath = ?",
                         (new_path, datetime.datetime.now(), old_path))
            conn.commit()

    def get_all_projects_without_uuid(self):
        """Get all projects that don't have an assigned UUID yet."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE mwq_uuid IS NULL OR mwq_uuid = ''")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def migrate_legacy_filenames_to_uuid(self):
        """Auto-assign UUIDs to projects that don't have them."""
        import uuid
        
        stats = {
            "migrated": 0,
            "errors": []
        }
        
        legacy_projects = self.get_all_projects_without_uuid()
        
        for project in legacy_projects:
            try:
                new_uuid = str(uuid.uuid4())
                self.set_project_uuid(project['id'], new_uuid)
                stats["migrated"] += 1
            except Exception as err:
                stats["errors"].append({
                    "project": project.get('name', 'Unknown'),
                    "error": str(err)
                })
        
        return stats

    # ============= Quote Numbering Methods =============

    def get_quote_counter(self, date: datetime.date, prefix: str = "OD") -> int:
        """Get current counter for a date and prefix."""
        date_str = date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT counter FROM quote_numbers WHERE date = ? AND prefix = ?",
                (date_str, prefix)
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def update_quote_counter(self, date: datetime.date, prefix: str = "OD", new_counter: int = 0):
        """Update counter for a date and prefix."""
        date_str = date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Use INSERT OR REPLACE for atomic update
            cursor.execute('''
                INSERT OR REPLACE INTO quote_numbers (date, prefix, counter, last_updated)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (date_str, prefix, new_counter))
            conn.commit()

    def increment_quote_counter(self, date: datetime.date, prefix: str = "OD") -> int:
        """Increment counter and return new value."""
        current = self.get_quote_counter(date, prefix)
        new_value = current + 1
        self.update_quote_counter(date, prefix, new_value)
        return new_value

    def reset_quote_counter(self, date: datetime.date, prefix: str = "OD"):
        """Reset counter to 0 for a date and prefix."""
        self.update_quote_counter(date, prefix, 0)

    def get_all_quote_counters_for_date(self, date: datetime.date):
        """Get all prefix counters for a specific date."""
        date_str = date.isoformat()
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT prefix, counter FROM quote_numbers WHERE date = ?",
                (date_str,)
            )
            rows = cursor.fetchall()
            return {row['prefix']: row['counter'] for row in rows}

    def get_quote_stats_for_date(self, date: datetime.date):
        """Get numbering stats for a date."""
        date_str = date.isoformat()
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM quote_numbers WHERE date = ?",
                (date_str,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def export_quote_numbering_stats(self, start_date: datetime.date, end_date: datetime.date):
        """Export numbering stats for a date range."""
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date, prefix, counter, last_updated FROM quote_numbers
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC, prefix
            ''', (start_str, end_str))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    def update_project_export_history(self, project_id: int, export_refs: str):
        """Update the devis_refs field with export history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE projects SET devis_refs = ? WHERE id = ?",
                (export_refs, project_id)
            )
            conn.commit()