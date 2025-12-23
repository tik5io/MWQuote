import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Union

class CostType(Enum):
    MATERIAL = "Matière"
    SUBCONTRACTING = "Sous-traitance"
    INTERNAL_OPERATION = "Opération interne"
    MARGIN = "Marge"

class PricingType(Enum):
    PER_UNIT = "Par unité"  # Prix par unité (pièce, mètre, kg, etc.)
    TIERED = "Échelons"  # Tarification par échelons de quantité

@dataclass
class PricingTier:
    """Un échelon de tarification avec plage de quantité"""
    min_quantity: int = 0  # Quantité minimale pour cet échelon
    max_quantity: Optional[int] = None  # Quantité maximale (None = illimité)
    fixed_price: float = 0.0  # Part fixe du tarif pour cet échelon
    unit_price: float = 0.0  # Part unitaire pour cet échelon
    description: str = ""  # Description optionnelle

    def applies_to_quantity(self, quantity: Union[int, float]) -> bool:
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
    # For legacy/simple PER_UNIT pricing (using a virtual 0-inf tier)
    fixed_price: float = 0.0
    unit_price: float = 0.0
    unit: str = "pièce"
    # For TIERED pricing
    tiers: List[PricingTier] = None

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = []

    def calculate_price(self, total_quantity: Union[int, float] = 1) -> float:
        """Calcule le prix selon le type de tarification"""
        match self.pricing_type:
            case PricingType.PER_UNIT:
                return self.fixed_price + (self.unit_price * total_quantity)
            case PricingType.TIERED:
                return self._calculate_tiered_price(total_quantity)

    def _calculate_tiered_price(self, total_quantity: Union[int, float]) -> float:
        """Calcule le prix avec tarification par échelons"""
        if not self.tiers:
            return 0.0

        tier = self.get_applicable_tier(total_quantity)
        if not tier:
            # Si aucun échelon ne correspond, prendre le plus proche
            tier = sorted(self.tiers, key=lambda t: abs(t.min_quantity - total_quantity))[0]

        return tier.fixed_price + (tier.unit_price * total_quantity)

    def get_applicable_tier(self, total_quantity: Union[int, float]) -> Optional[PricingTier]:
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
    # For internal operations
    fixed_time: float = 0.0  # legacy flat time
    per_piece_time: float = 0.0  # legacy per piece time
    # For margins
    margin_percentage: float = 0.0
    # Conversion parameters
    quantity_multiplier: float = 1.0  # units per piece (e.g. meter/piece)
    # Supplier quote reference
    supplier_quote_ref: Optional[str] = None
    # Common
    comment: Optional[str] = None

    def calculate_value(self, total_pieces: int = 1) -> float:
        """Calculate the total value based on cost type"""
        # Base quantity conversion
        units = total_pieces * self.quantity_multiplier
        
        match self.cost_type:
            case CostType.MATERIAL | CostType.SUBCONTRACTING:
                return self.pricing.calculate_price(units)
            case CostType.INTERNAL_OPERATION:
                # Internal operations also use the PricingStructure if set, 
                # but fallback to fixed_time + per_piece_time for legacy compatibility
                if self.pricing and (self.pricing.unit_price != 0 or self.pricing.fixed_price != 0 or self.pricing.tiers):
                    return self.pricing.calculate_price(units)
                return self.fixed_time + (self.per_piece_time * units)
            case CostType.MARGIN:
                return 0.0
            case _:
                return 0.0
