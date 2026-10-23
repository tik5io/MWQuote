import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Union
from .document import Document
from .phase import ToolingBilling

class CostType(Enum):
    MATERIAL = "Matière"
    SUBCONTRACTING = "Sous-traitance"
    INTERNAL_OPERATION = "Opération interne"
    TOOLING = "Outillage"

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
class ToolingLine:
    """Ligne de détail d'un outillage (réglage, programme, posage…)."""
    label: str = ""
    quantity: float = 1.0
    unit: str = ""
    unit_price: float = 0.0

    @property
    def total(self) -> float:
        return float(self.quantity or 0.0) * float(self.unit_price or 0.0)


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
                tiers_list = [t for t in (self.tiers or []) if t is not None]
                if not tiers_list:
                    return self.fixed_price, 0.0
                tier = self.get_applicable_tier(total_quantity)
                if not tier:
                    tier = sorted(tiers_list, key=lambda t: abs(t.min_quantity - total_quantity))[0]
                return self.fixed_price, tier.unit_price * total_quantity

    def _calculate_tiered_price(self, total_quantity: Union[int, float]) -> float:
        """Calcule le prix avec tarification par échelons"""
        tiers_list = [t for t in (self.tiers or []) if t is not None]
        if not tiers_list:
            return self.fixed_price

        tier = self.get_applicable_tier(total_quantity)
        if not tier:
            # Si aucun échelon ne correspond, prendre le plus proche
            tier = sorted(tiers_list, key=lambda t: abs(t.min_quantity - total_quantity))[0]

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
    quantity_per_piece_is_inverse: bool = False  # If True, value is pieces per quote unit (e.g., pieces/plate)
    # Margin
    margin_rate: float = 0.0  # Percentage (e.g. 20 for 20%)
    # Documents (for SUBCONTRACTING/Quotes)
    documents: List[Document] = field(default_factory=list)
    # Common
    comment: Optional[str] = None
    client_comment: Optional[str] = None
    supplier_quote_ref: Optional[str] = None # Still useful for the reference ID
    is_active: bool = True  # Used for multi-offer subcontracting
    is_temps_masque: bool = False  # If True, this internal operation is in masked time (0s effective cycle time)
    # Outillage : surcharge du mode de facturation de la phase (None = mode de la phase).
    # S'applique aux lignes Outillage et à l'outillage fournisseur ci-dessous.
    tooling_billing: Optional["ToolingBilling"] = None
    # Outillage fournisseur rattaché à l'offre (Matière / Sous-traitance) :
    # montant de l'outil et pièces fournies avec (non facturées au prix pièce).
    # (legacy : l'outillage fournisseur est désormais une ligne Outillage à part
    # entière ; ces deux champs ne sont plus renseignés, la conversion les migre.)
    tooling_amount: float = 0.0
    tooling_included_pieces: int = 0
    # Ligne Outillage : détail ligne à ligne ; si renseigné, le montant
    # (pricing.fixed_price) est la somme des lignes.
    tooling_lines: List[ToolingLine] = field(default_factory=list)
    # Ligne Outillage : offre d'achat à laquelle l'outil est rattaché (clé de la
    # ligne dans l'opération). None = outil commun à toute l'opération.
    # Les pièces incluses avec l'outil (tooling_included_pieces) sont gratuites
    # sur les lignes d'achat concernées.
    linked_offer: Optional[str] = None

    # Étape interne — valorisation SÉRIE. None = hérité de la saisie Proto/Lot.
    serie_cycle_time_s: Optional[float] = None     # temps de cycle (s)
    serie_pieces_per_cycle: Optional[float] = None  # pièces par cycle (posage multiple…)
    serie_setup_h: Optional[float] = None          # réglage par campagne (h)
    serie_hourly_rate: Optional[float] = None      # taux de l'étape en série (€/h)

    def __post_init__(self):
        # Pièces gratuites (outillage de l'opération) : posé par Operation, non persisté.
        self._free_pieces: Optional[int] = None

    # --- Valeurs héritées (calculées depuis la saisie Proto/Lot) ---

    def _conv_factor(self) -> float:
        return self.conversion_factor if self.conversion_factor not in (None, 0) else 1.0

    def inherited_serie_cycle_time_s(self) -> float:
        f = self._conv_factor()
        base = (self.per_piece_time or 0.0) * 3600.0
        return base * f if self.conversion_type == ConversionType.MULTIPLY else base

    def inherited_serie_pieces_per_cycle(self) -> float:
        return self._conv_factor() if self.conversion_type == ConversionType.DIVIDE else 1.0

    def inherited_serie_setup_h(self) -> float:
        f = self._conv_factor()
        ft = self.fixed_time or 0.0
        return ft / f if self.conversion_type == ConversionType.DIVIDE else ft * f

    # --- Valeurs effectives en série (saisie Série sinon héritage) ---

    def serie_cycle_s(self, override: Optional[float] = None) -> float:
        if override is not None:
            return override
        return self.serie_cycle_time_s if self.serie_cycle_time_s is not None else self.inherited_serie_cycle_time_s()

    def serie_pieces(self) -> float:
        n = self.serie_pieces_per_cycle if self.serie_pieces_per_cycle is not None else self.inherited_serie_pieces_per_cycle()
        return n if n and n > 0 else 1.0

    def serie_rate(self, override: Optional[float] = None) -> float:
        if override is not None:
            return override
        return self.serie_hourly_rate if self.serie_hourly_rate is not None else (self.hourly_rate or 0.0)

    def serie_setup(self) -> float:
        return self.serie_setup_h if self.serie_setup_h is not None else self.inherited_serie_setup_h()

    def serie_time_per_piece_h(self, cycle_override: Optional[float] = None) -> float:
        """Temps machine par pièce en série (h), 0 si temps masqué."""
        if getattr(self, "is_temps_masque", False):
            return 0.0
        if cycle_override is None and self.serie_cycle_time_s is None and self.serie_pieces_per_cycle is None:
            # Héritage complet : formule historique exacte (aucun écart d'arrondi)
            f = self._conv_factor()
            pt = self.per_piece_time or 0.0
            return pt / f if self.conversion_type == ConversionType.DIVIDE else pt * f
        return self.serie_cycle_s(cycle_override) / self.serie_pieces() / 3600.0

    def serie_is_inherited(self) -> bool:
        return all(v is None for v in (self.serie_cycle_time_s, self.serie_pieces_per_cycle,
                                       self.serie_setup_h, self.serie_hourly_rate))

    def tooling_lines_total(self) -> float:
        return sum(line.total for line in self.tooling_lines)

    def apply_tooling_lines(self) -> None:
        """Reporte la somme des lignes dans le montant de l'outillage."""
        if self.cost_type == CostType.TOOLING and self.tooling_lines:
            if self.pricing is None:
                self.pricing = PricingStructure(PricingType.PER_UNIT)
            self.pricing.fixed_price = self.tooling_lines_total()

    @property
    def has_supplier_tooling(self) -> bool:
        return (self.cost_type in (CostType.MATERIAL, CostType.SUBCONTRACTING)
                and (self.tooling_amount or 0) > 0)

    def supplier_tooling_item(self) -> "CostItem":
        """Ligne d'outillage virtuelle représentant l'outil fournisseur (non persistée)."""
        item = CostItem(
            name=f"Outillage {self.name}",
            cost_type=CostType.TOOLING,
            pricing=PricingStructure(PricingType.PER_UNIT, fixed_price=float(self.tooling_amount or 0.0),
                                     unit="forfait"),
            tooling_billing=self.tooling_billing,
        )
        item.supplier_parent = self
        return item

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
        if self.quantity_per_piece_is_inverse:
            import math
            conv = self.quantity_per_piece if self.quantity_per_piece not in (None, 0) else 1.0
            quote_qty_needed = math.ceil(total_pieces / conv)
        else:
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
