# tests/test_quote_numbering.py
"""
Tests pour le système de numérotation de quotes persistant.
"""

import unittest
import tempfile
import os
import shutil
import datetime
from infrastructure.database import Database
from infrastructure.quote_numbering_service import QuoteNumberingService


class TestQuoteNumbering(unittest.TestCase):
    """Tests pour la numérotation de quotes."""
    
    def setUp(self):
        """Préparation des tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
        self.numbering = QuoteNumberingService(self.db)
    
    def tearDown(self):
        """Nettoyage après tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_first_quote_number(self):
        """Test premier numéro de quote."""
        quote_num, counter = self.numbering.get_next_quote_number("OD")
        
        self.assertEqual(counter, 1)
        self.assertIn("OD", quote_num)
        self.assertIn("_001", quote_num)
    
    def test_incremental_numbering(self):
        """Test l'incrémentation correcte."""
        counters = []
        for i in range(5):
            _, counter = self.numbering.get_next_quote_number("OD")
            counters.append(counter)
        
        # Doit être 1, 2, 3, 4, 5
        self.assertEqual(counters, [1, 2, 3, 4, 5])
    
    def test_format_quote_number(self):
        """Test le format du numéro de quote."""
        quote_num, _ = self.numbering.get_next_quote_number("OD")
        
        # Format: OD{YYMMDD}_{counter:03d}
        # Example: OD260202_001
        parts = quote_num.split("_")
        self.assertEqual(len(parts), 2)
        self.assertIn("OD", parts[0])
        self.assertEqual(parts[1], "001")
    
    def test_with_subversion(self):
        """Test avec sous-version."""
        full_ref = self.numbering.get_quote_number_with_subversion("OD", 1)
        
        # Format: {quote_num}-{sub_version}
        # Example: OD260202_001-1
        self.assertIn("-1", full_ref)
        self.assertIn("OD", full_ref)
    
    def test_different_prefixes(self):
        """Test avec différents préfixes."""
        num1, cnt1 = self.numbering.get_next_quote_number("OD")
        num2, cnt2 = self.numbering.get_next_quote_number("QT")
        
        # Counters indépendants par préfixe
        self.assertEqual(cnt1, 1)
        self.assertEqual(cnt2, 1)
        
        # Numéros différents
        self.assertNotEqual(num1, num2)
        self.assertIn("OD", num1)
        self.assertIn("QT", num2)
    
    def test_persistence_across_instances(self):
        """Test la persistance entre instances."""
        # Première instance
        num1, cnt1 = self.numbering.get_next_quote_number("OD")
        self.assertEqual(cnt1, 1)
        
        # Nouvelle instance (simule nouvelle session)
        numbering2 = QuoteNumberingService(self.db)
        num2, cnt2 = numbering2.get_next_quote_number("OD")
        self.assertEqual(cnt2, 2)
    
    def test_current_counter_without_increment(self):
        """Test lecture du counter sans incrémenter."""
        self.numbering.get_next_quote_number("OD")
        self.numbering.get_next_quote_number("OD")
        
        current = self.numbering.get_current_counter("OD")
        self.assertEqual(current, 2)
        
        # Vérifier que le prochain est 3 (pas affecté par lecture)
        _, cnt = self.numbering.get_next_quote_number("OD")
        self.assertEqual(cnt, 3)
    
    def test_reset_counter(self):
        """Test reset du counter."""
        self.numbering.get_next_quote_number("OD")
        self.numbering.get_next_quote_number("OD")
        
        today = datetime.date.today()
        self.numbering.reset_counter_for_date(today, "OD")
        
        current = self.numbering.get_current_counter("OD")
        self.assertEqual(current, 0)
    
    def test_different_dates(self):
        """Test que les counters sont par date."""
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        
        # Counter pour aujourd'hui
        _, cnt_today = self.numbering.get_next_quote_number("OD")
        self.assertEqual(cnt_today, 1)
        
        # Counter pour hier devrait être indépendant
        cnt_yesterday = self.db.get_quote_counter(yesterday, "OD")
        self.assertEqual(cnt_yesterday, 0)
    
    def test_stats_for_date(self):
        """Test les stats d'une date."""
        self.numbering.get_next_quote_number("OD")
        self.numbering.get_next_quote_number("OD")
        self.numbering.get_next_quote_number("QT")
        
        today = datetime.date.today()
        stats = self.numbering.get_stats_for_date(today)
        
        self.assertEqual(stats["date"], today.isoformat())
        self.assertEqual(stats["total_quotes"], 2)  # 2 entrées (OD, QT)


class TestDatabaseQuoteNumbering(unittest.TestCase):
    """Tests pour les méthodes de DB."""
    
    def setUp(self):
        """Préparation des tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
    
    def tearDown(self):
        """Nettoyage après tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_quote_table_created(self):
        """Test que la table est créée."""
        self.db.init_quote_numbering_table()
        
        # Vérifier qu'on peut insérer
        today = datetime.date.today()
        self.db.update_quote_counter(today, "OD", 5)
        
        counter = self.db.get_quote_counter(today, "OD")
        self.assertEqual(counter, 5)
    
    def test_increment_returns_new_value(self):
        """Test que increment retourne la nouvelle valeur."""
        today = datetime.date.today()
        
        new_val = self.db.increment_quote_counter(today, "OD")
        self.assertEqual(new_val, 1)
        
        new_val = self.db.increment_quote_counter(today, "OD")
        self.assertEqual(new_val, 2)
    
    def test_get_all_counters_for_date(self):
        """Test récupération tous les counters."""
        today = datetime.date.today()
        
        self.db.update_quote_counter(today, "OD", 10)
        self.db.update_quote_counter(today, "QT", 5)
        
        counters = self.db.get_all_quote_counters_for_date(today)
        
        self.assertEqual(len(counters), 2)
        self.assertEqual(counters["OD"], 10)
        self.assertEqual(counters["QT"], 5)


if __name__ == '__main__':
    unittest.main()
