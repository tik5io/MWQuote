# tests/test_file_manager_migration.py
"""
Tests pour FileManager et la migration UUID.
"""

import unittest
import tempfile
import os
import shutil
from infrastructure.file_manager import FileManager
from infrastructure.database import Database


class TestFileManager(unittest.TestCase):
    """Tests pour FileManager."""
    
    def setUp(self):
        """Préparation des tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
    
    def tearDown(self):
        """Nettoyage après tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_generate_uuid(self):
        """Test génération UUID."""
        uuid1 = FileManager.generate_uuid()
        uuid2 = FileManager.generate_uuid()
        
        self.assertIsNotNone(uuid1)
        self.assertIsNotNone(uuid2)
        self.assertNotEqual(uuid1, uuid2)
        self.assertEqual(len(uuid1), 36)  # UUID format
    
    def test_generate_mwq_filename_with_uuid(self):
        """Test génération filename avec UUID."""
        filename = FileManager.generate_mwq_filename("QUOTE-001", "Widget Case", use_uuid=True)
        
        self.assertTrue(filename.endswith(".mwq"))
        self.assertIn("quote001", filename.lower())
        self.assertIn("widget", filename.lower())
        
        # Extrait UUID possible
        uuid = FileManager.extract_uuid_from_filename(filename)
        self.assertIsNotNone(uuid)
    
    def test_generate_mwq_filename_legacy(self):
        """Test génération filename legacy (sans UUID)."""
        filename = FileManager.generate_mwq_filename("QUOTE-001", "Widget Case", use_uuid=False)
        
        self.assertTrue(filename.endswith(".mwq"))
        self.assertIn("quote001", filename.lower())
        
        # Pas d'UUID extractible
        uuid = FileManager.extract_uuid_from_filename(filename)
        self.assertIsNone(uuid)
    
    def test_extract_uuid_from_filename(self):
        """Test extraction UUID depuis filename."""
        # Filename avec UUID
        filename_with_uuid = "550e8400-e29b-41d4-a716-446655440000_quote001.mwq"
        uuid = FileManager.extract_uuid_from_filename(filename_with_uuid)
        self.assertEqual(uuid, "550e8400-e29b-41d4-a716-446655440000")
        
        # Filename sans UUID
        filename_no_uuid = "quote001_widget.mwq"
        uuid = FileManager.extract_uuid_from_filename(filename_no_uuid)
        self.assertIsNone(uuid)
    
    def test_get_safe_filename(self):
        """Test sanitization de filename."""
        safe = FileManager.get_safe_filename("QUOTE-001", "Widget Case/Version 2")
        
        self.assertNotIn("/", safe)
        self.assertNotIn(":", safe)
        self.assertTrue(len(safe) <= 50)
    
    def test_get_all_mwq_files(self):
        """Test recherche tous les fichiers MWQ."""
        # Créer quelques fichiers
        os.makedirs(os.path.join(self.temp_dir, "subdir"), exist_ok=True)
        
        mwq_files = [
            "file1.mwq",
            "file2.mwq",
            "subdir/file3.mwq",
            "file4.txt"  # Pas un MWQ
        ]
        
        for f in mwq_files:
            path = os.path.join(self.temp_dir, f)
            open(path, "w").close()
        
        # Rechercher MWQ
        found = FileManager.get_all_mwq_files(self.temp_dir)
        
        # Doit trouver 3 fichiers .mwq
        self.assertEqual(len(found), 3)
        self.assertTrue(all(f.endswith(".mwq") for f in found))
    
    def test_is_valid_uuid(self):
        """Test validation UUID."""
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        invalid_uuid = "not-a-uuid"
        
        self.assertTrue(FileManager._is_valid_uuid(valid_uuid))
        self.assertFalse(FileManager._is_valid_uuid(invalid_uuid))


class TestMigration(unittest.TestCase):
    """Tests pour migration UUID."""
    
    def setUp(self):
        """Préparation des tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.old_dir = os.path.join(self.temp_dir, "old")
        self.new_dir = os.path.join(self.temp_dir, "new")
        os.makedirs(self.old_dir)
        os.makedirs(self.new_dir)
        
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
    
    def tearDown(self):
        """Nettoyage après tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_migrate_to_uuid_naming(self):
        """Test migration files vers UUID naming."""
        # Créer fichiers legacy
        legacy_files = [
            "quote001.mwq",
            "widget_case.mwq",
            "client_v2.mwq"
        ]
        
        for f in legacy_files:
            path = os.path.join(self.old_dir, f)
            with open(path, "w") as fp:
                fp.write("test content")
        
        # Migrer
        stats = FileManager.migrate_to_uuid_naming(self.old_dir, self.db)
        
        self.assertEqual(stats["scanned"], 3)
        self.assertEqual(stats["migrated"], 3)
        self.assertEqual(stats["already_uuid"], 0)
        
        # Vérifier que les fichiers sont renommés
        remaining = FileManager.get_all_mwq_files(self.old_dir)
        for f in remaining:
            uuid = FileManager.extract_uuid_from_filename(os.path.basename(f))
            self.assertIsNotNone(uuid)  # Tous doivent avoir UUID maintenant
    
    def test_relocate_files(self):
        """Test relocalisation de fichiers."""
        # Créer fichiers dans ancien dossier
        legacy_files = [
            "quote001.mwq",
            "widget_case.mwq"
        ]
        
        for f in legacy_files:
            path = os.path.join(self.old_dir, f)
            with open(path, "w") as fp:
                fp.write("test content")
        
        # Relocaliser
        stats = FileManager.relocate_files(self.old_dir, self.new_dir, self.db)
        
        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["relocated"], 2)
        
        # Vérifier fichiers copiés en nouveau dossier
        new_files = FileManager.get_all_mwq_files(self.new_dir)
        self.assertEqual(len(new_files), 2)
        
        # Vérifier fichiers renommés en UUID
        for f in new_files:
            uuid = FileManager.extract_uuid_from_filename(os.path.basename(f))
            self.assertIsNotNone(uuid)


class TestDatabaseUUID(unittest.TestCase):
    """Tests pour support UUID en database."""
    
    def setUp(self):
        """Préparation des tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
    
    def tearDown(self):
        """Nettoyage après tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_set_and_get_uuid(self):
        """Test set/get UUID."""
        # Créer projet
        project_data = {
            'name': 'Test Project',
            'reference': 'TEST-001',
            'client': 'Test Client',
            'filepath': '/test/path.mwq',
            'drawing_filename': None,
            'status': 'En construction',
            'export_history': []
        }
        
        project_id = self.db.upsert_project(project_data)
        
        # Assigner UUID
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.db.set_project_uuid(project_id, test_uuid)
        
        # Récupérer projet par UUID
        project = self.db.get_project_by_uuid(test_uuid)
        self.assertIsNotNone(project)
        self.assertEqual(project['id'], project_id)
        self.assertEqual(project['mwq_uuid'], test_uuid)
    
    def test_migrate_legacy_filenames_to_uuid(self):
        """Test auto-assignment UUID aux legacy projects."""
        # Créer 3 projets sans UUID
        for i in range(3):
            project_data = {
                'name': f'Project {i}',
                'reference': f'REF-{i}',
                'client': f'Client {i}',
                'filepath': f'/test/path{i}.mwq',
                'drawing_filename': None,
                'status': 'En construction',
                'export_history': []
            }
            self.db.upsert_project(project_data)
        
        # Migrer
        stats = self.db.migrate_legacy_filenames_to_uuid()
        
        self.assertEqual(stats['migrated'], 3)
        
        # Vérifier que tous les projets ont un UUID
        legacy = self.db.get_all_projects_without_uuid()
        self.assertEqual(len(legacy), 0)
    
    def test_update_filepath(self):
        """Test update filepath."""
        # Créer projet
        project_data = {
            'name': 'Test',
            'reference': 'TEST',
            'client': 'Client',
            'filepath': '/old/path.mwq',
            'drawing_filename': None,
            'status': 'En construction',
            'export_history': []
        }
        
        project_id = self.db.upsert_project(project_data)
        
        # Update filepath par ID
        new_path = '/new/path.mwq'
        self.db.update_filepath(project_id, new_path)
        
        # Vérifier
        projects = self.db.search_projects()
        found = [p for p in projects if p['id'] == project_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['filepath'], new_path)


if __name__ == '__main__':
    unittest.main()
