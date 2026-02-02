# infrastructure/quote_numbering_service.py
"""
Service for managing sequential quote numbering across sessions.

Maintains a persistent counter in the database to ensure unique quote numbers
per day, preventing duplicate references when multiple quotes are created
in the same session or across different sessions.

Format: {prefix}{date}_{counter:03d}{sub_version}
Example: OD260202_001-1 (OD prefix, Feb 2 2026, counter 001, sub-version 1)
"""

import datetime
from typing import Optional, Dict, Tuple
from infrastructure.database import Database


class QuoteNumberingService:
    """Service for managing sequential quote numbers with persistence."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure quote_numbers table exists."""
        self.db.init_quote_numbering_table()

    def get_next_quote_number(self, prefix: str = "OD") -> Tuple[str, int]:
        """
        Get the next sequential quote number for today.
        
        Returns:
            (quote_number: str, counter: int)
            
        Example:
            ("OD260202_001", 1) → use as "OD260202_001-1" in export
        """
        today = datetime.date.today()
        date_str = today.strftime("%y%m%d")
        
        # Get current counter for today
        current = self.db.get_quote_counter(today, prefix)
        next_counter = current + 1
        
        # Update DB with new counter
        self.db.update_quote_counter(today, prefix, next_counter)
        
        # Format quote number
        quote_number = f"{prefix}{date_str}_{next_counter:03d}"
        
        return quote_number, next_counter

    def get_quote_number_with_subversion(self, prefix: str = "OD", sub_version: int = 1) -> str:
        """
        Get full quote reference with sub-version.
        
        Returns:
            str: Full reference like "OD260202_001-1"
        """
        quote_num, counter = self.get_next_quote_number(prefix)
        return f"{quote_num}-{sub_version}"

    def get_current_counter(self, prefix: str = "OD") -> int:
        """Get current counter for today (without incrementing)."""
        today = datetime.date.today()
        return self.db.get_quote_counter(today, prefix)

    def get_quote_counter_for_date(self, date: datetime.date, prefix: str = "OD") -> int:
        """Get counter for a specific date."""
        return self.db.get_quote_counter(date, prefix)

    def get_stats_for_date(self, date: datetime.date) -> Dict:
        """Get numbering statistics for a date."""
        stats = self.db.get_quote_stats_for_date(date)
        return {
            "date": date.isoformat(),
            "total_quotes": len(stats),
            "by_prefix": {}
        }

    def reset_counter_for_date(self, date: datetime.date, prefix: str = "OD"):
        """Reset counter for a specific date (admin use only)."""
        self.db.reset_quote_counter(date, prefix)

    def get_all_counters_for_date(self, date: datetime.date) -> Dict[str, int]:
        """Get all prefix counters for a date."""
        return self.db.get_all_quote_counters_for_date(date)

    def export_numbering_stats(self, start_date: datetime.date, end_date: datetime.date) -> Dict:
        """Export numbering statistics for a date range."""
        return self.db.export_quote_numbering_stats(start_date, end_date)
