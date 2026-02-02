import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Union
from .document import Document

class CostType(Enum):
    MATERIAL = "Matière"
    SUBCONTRACTING = "Sous-traitance"
    INTERNAL_OPERATION = "Opération interne"

class PricingType(Enum):
    PER_UNIT = "Par unité"  # Prix par unité (pièce, mètre, kg, etc.)
    TIERED = "Échelons"  # Tarification par échelons de quantité

class ConversionType(Enum):
    MULTIPLY = "Multiplier"  # units = pieces * factor (ex: 2 meters/piece)
    DIVIDE = "Diviser"     # units = pieces / factor (ex: 100 pieces/hour)

@dataclass
class PricingTier:
    """Un échelon de tarification avec seuil de quantité minimale"""
    min_quantity: int = 0  # Quantité minimale pour cet échelon
    unit_price: float = 0.0  # Prix unitaire pour cet échelon
    description: str = ""  # Description optionnelle

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

    def calculate_components(self, total_quantity: Union[int, float] = 1) -> (float, float):
        """Retourne (part fixe, part variable) du prix"""
        match self.pricing_type:
            case PricingType.PER_UNIT:
                return self.fixed_price, self.unit_price * total_quantity
            case PricingType.TIERED:
                tier = self.get_applicable_tier(total_quantity)
                if not tier:
                    tier = sorted(self.tiers, key=lambda t: abs(t.min_quantity - total_quantity))[0]
                return self.fixed_price, tier.unit_price * total_quantity

    def _calculate_tiered_price(self, total_quantity: Union[int, float]) -> float:
        """Calcule le prix avec tarification par échelons"""
        if not self.tiers:
            return 0.0

        tier = self.get_applicable_tier(total_quantity)
        if not tier:
            # Si aucun échelon ne correspond, prendre le plus proche
            tier = sorted(self.tiers, key=lambda t: abs(t.min_quantity - total_quantity))[0]

        return self.fixed_price + (tier.unit_price * total_quantity)

    def get_applicable_tier(self, total_quantity: Union[int, float]) -> Optional[PricingTier]:
        """Retourne l'échelon applicable pour une quantité donnée (le plus haut min_quantity <= Q)"""
        applicable = None
        for tier in sorted(self.tiers, key=lambda t: t.min_quantity):
            if tier.min_quantity <= total_quantity:
                applicable = tier
            else:
                break
        return applicable

@dataclass
class CostItem:
    name: str
    cost_type: CostType
    pricing: PricingStructure
    # For internal operations
    fixed_time: float = 0.0  # legacy flat time
    per_piece_time: float = 0.0  # legacy per piece time (Hours)
    hourly_rate: float = 0.0  # Euro/Hour
    # Conversion parameters
    conversion_type: ConversionType = ConversionType.MULTIPLY
    conversion_factor: float = 1.0  # units per piece (if MULTIPLY) or pieces per unit (if DIVIDE)
    # Quantity per piece (for MATERIAL/SUBCONTRACTING)
    quantity_per_piece: float = 1.0  # How many quote units used per produced piece (e.g., 0.1m/piece)
    # Margin
    margin_rate: float = 0.0  # Percentage (e.g. 20 for 20%)
    # Documents (for SUBCONTRACTING/Quotes)
    documents: List[Document] = field(default_factory=list)
    # Common
    comment: Optional[str] = None
    supplier_quote_ref: Optional[str] = None # Still useful for the reference ID
    is_active: bool = True  # Used for multi-offer subcontracting

    @property
    def supplier_quote_filename(self):
        """Legacy compatibility."""
        return self.documents[0].filename if self.documents else None

    @property
    def supplier_quote_data(self):
        """Legacy compatibility."""
        return self.documents[0].data if self.documents else None

    def get_moq(self) -> int:
        """Get Minimum Order Quantity (MOQ) for SUBCONTRACTING costs.
        Returns the minimum quantity from configured tiers, or 0 if no tiers.
        """
        if self.cost_type != CostType.SUBCONTRACTING:
            return 0
        
        if self.pricing and self.pricing.pricing_type == PricingType.TIERED and self.pricing.tiers:
            return min(tier.min_quantity for tier in self.pricing.tiers)
        
        return 0
    
    def is_below_moq(self, total_pieces: int) -> bool:
        """Check if quantity is below MOQ for SUBCONTRACTING costs."""
        moq = self.get_moq()
        if moq == 0:
            return False
        # Check if quote quantity needed is below MOQ
        quote_qty_needed = total_pieces * self.quantity_per_piece
        return quote_qty_needed < moq

    def calculate_value(self, total_pieces: int = 1) -> float:
        """Calculate the unit cost value by delegating to Calculator."""
        from .calculator import Calculator
        result = Calculator.calculate_item(self, total_pieces)
        return result.unit_cost_converted

    def calculate_components(self, total_pieces: int = 1) -> (float, float):
        """Calcule les composantes (Fixe, Variable) par PIÈCE."""
        from .calculator import Calculator
        result = Calculator.calculate_item(self, total_pieces)
        # Return per-piece components (converted)
        # We need to backtrack from result.unit_sale_price if we want converted components
        # Actually Calculator already returns fixed_part/variable_part as per-piece sale prices.
        # But here we want the COST components (converted but before margin).
        # Let's adjust Calculator to return cost components as well, or calculate them here.
        m_rate = min(self.margin_rate, 99.9)
        m_factor = 1.0 / (1.0 - m_rate / 100.0)
        return result.fixed_part / m_factor, result.variable_part / m_factor

    def calculate_sale_components(self, total_pieces: int = 1) -> (float, float):
        """Calcule les composantes (Fixe, Variable) du prix de vente par PIÈCE."""
        from .calculator import Calculator
        result = Calculator.calculate_item(self, total_pieces)
        return result.fixed_part, result.variable_part

    def calculate_sale_price(self, total_pieces: int = 1) -> float:
        """Calculate the unit sale price by delegating to Calculator."""
        from .calculator import Calculator
        result = Calculator.calculate_item(self, total_pieces)
        return result.unit_sale_price
