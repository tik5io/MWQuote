# domain/cost.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

class CostType(Enum):
    MATERIAL = "Matière"
    SUBCONTRACTING = "Sous-traitance"
    INTERNAL_OPERATION = "Opération interne"
    MARGIN = "Marge"

class PricingType(Enum):
    FIXED = "Forfait"  # Prix fixe
    PER_UNIT = "Par unité"  # Prix par unité (pièce, mètre, kg, etc.)
    TIERED = "Échelons"  # Tarification par échelons de quantité

@dataclass
class PricingTier:
    """Un échelon de tarification avec plage de quantité"""
    min_quantity: int = 0  # Quantité minimale pour cet échelon
    max_quantity: Optional[int] = None  # Quantité maximale (None = illimité)
    unit_price: float = 0.0  # Prix unitaire pour cet échelon
    description: str = ""  # Description optionnelle (ex: "Remise 10%")

    def applies_to_quantity(self, quantity: int) -> bool:
        """Vérifie si cet échelon s'applique à la quantité donnée"""
        if quantity < self.min_quantity:
            return False
        if self.max_quantity is not None and quantity > self.max_quantity:
            return False
        return True

@dataclass
class PricingStructure:
    """Structure de tarification flexible"""
    pricing_type: PricingType
    # For FIXED pricing
    fixed_price: float = 0.0
    # For PER_UNIT pricing
    unit_price: float = 0.0
    unit: str = "pièce"  # unité: pièce, mètre, kg, litre, etc.
    # For TIERED pricing
    tiers: List[PricingTier] = None

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = []

    def calculate_price(self, total_quantity: int = 1) -> float:
        """Calcule le prix selon le type de tarification"""
        match self.pricing_type:
            case PricingType.FIXED:
                return self.fixed_price
            case PricingType.PER_UNIT:
                return self.unit_price * total_quantity
            case PricingType.TIERED:
                return self._calculate_tiered_price(total_quantity)

    def _calculate_tiered_price(self, total_quantity: int) -> float:
        """Calcule le prix avec tarification par échelons"""
        if not self.tiers:
            return 0.0

        # Trouver l'échelon applicable
        applicable_tier = None
        for tier in sorted(self.tiers, key=lambda t: t.min_quantity):
            if tier.applies_to_quantity(total_quantity):
                applicable_tier = tier
                break

        if applicable_tier:
            return applicable_tier.unit_price * total_quantity
        else:
            # Si aucun échelon ne correspond, prendre le dernier (quantité max)
            if self.tiers:
                last_tier = max(self.tiers, key=lambda t: t.min_quantity)
                return last_tier.unit_price * total_quantity
            return 0.0

    def get_applicable_tier(self, total_quantity: int) -> Optional[PricingTier]:
        """Retourne l'échelon applicable pour une quantité donnée"""
        for tier in sorted(self.tiers, key=lambda t: t.min_quantity):
            if tier.applies_to_quantity(total_quantity):
                return tier
        return None

@dataclass
class CostItem:
    name: str
    cost_type: CostType
    pricing: PricingStructure
    # For internal operations (if applicable)
    fixed_time: float = 0.0  # in hours
    per_piece_time: float = 0.0  # in hours per piece
    # For margins
    margin_percentage: float = 0.0
    # Supplier quote reference
    supplier_quote_ref: Optional[str] = None
    # Common
    comment: Optional[str] = None

    def calculate_value(self, total_pieces: int = 1) -> float:
        """Calculate the total value based on cost type"""
        match self.cost_type:
            case CostType.MATERIAL | CostType.SUBCONTRACTING:
                return self.pricing.calculate_price(total_pieces)
            case CostType.INTERNAL_OPERATION:
                return self.fixed_time + (self.per_piece_time * total_pieces)
            case CostType.MARGIN:
                return 0.0  # Margins are calculated separately
            case _:
                return 0.0
