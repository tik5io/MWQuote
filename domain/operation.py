from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .cost import CostItem, CostType, PricingStructure, PricingType
from .phase import PhaseContext, PhaseKind, ToolingBilling

SUBCONTRACTING_TYPOLOGY = "Sous-traitance"
INTERNAL_TYPOLOGY = "Interne"
TOOLING_TYPOLOGY = "OUTILLAGE"  # legacy : plus jamais créé, migré en lignes Outillage

# Les deux seules typologies d'opération du modèle propre.
OPERATION_TYPOLOGIES = [INTERNAL_TYPOLOGY, SUBCONTRACTING_TYPOLOGY]


def normalize_typology(typology: str) -> str:
    """Ramène une typologie historique (texte libre) à {Interne, Sous-traitance}.

    « Sous-traitance » reste Sous-traitance ; tout le reste (familles d'usinage
    « Microdécoupe », « Tournage »… et valeurs vides) devient Interne.
    L'ancienne opération OUTILLAGE est convertie en amont (lignes Outillage)
    donc n'arrive pas ici. La famille d'origine n'est pas perdue : voir
    family_from_typology.
    """
    return SUBCONTRACTING_TYPOLOGY if (typology or "").strip() == SUBCONTRACTING_TYPOLOGY else INTERNAL_TYPOLOGY


def family_from_typology(typology: str) -> str:
    """Famille d'usinage portée par une ancienne typologie (« » si aucune)."""
    value = (typology or "").strip()
    if value in ("", SUBCONTRACTING_TYPOLOGY, INTERNAL_TYPOLOGY) or value.upper() == TOOLING_TYPOLOGY:
        return ""
    return value

@dataclass
class Operation:
    code: str
    label: str
    typology: str = ""
    comment: str = ""
    template_id: int | None = None
    template_name: str = ""
    template_snapshot: dict = field(default_factory=dict)
    template_drift_score: float = 0.0
    costs: Dict[str, CostItem] = field(default_factory=dict)
    total_pieces: int = 1  # Number of pieces for per-piece calculations
    # Famille d'usinage (Microdécoupe, Tournage…) : descriptive, hors typologie.
    # Alimente les analyses par famille et les exports ; n'influe pas sur le calcul.
    family: str = ""

    @property
    def display_family(self) -> str:
        """Famille à afficher/analyser : la famille, à défaut la typologie."""
        return self.family or self.typology

    def __post_init__(self):
        # Contexte de phase courant (non persisté) : posé par Project.operations.
        # None = aucun filtre de phase (comportement historique).
        self._phase_ctx: Optional[PhaseContext] = None

    # ------------------------------------------------------------------ phases

    @property
    def phase_ctx(self) -> Optional[PhaseContext]:
        return getattr(self, "_phase_ctx", None)

    def set_phase_context(self, ctx: Optional[PhaseContext]) -> None:
        self._phase_ctx = ctx
        self.refresh_free_pieces()

    # ------------------------------------------------------------ pièces gratuites

    _PURCHASE_TYPES = (CostType.MATERIAL, CostType.SUBCONTRACTING)

    def free_pieces_for(self, cost: CostItem) -> int:
        """Pièces livrées avec l'outillage, gratuites sur cette ligne d'achat.

        Somme des pièces incluses des outillages de l'opération qui lui sont
        rattachés (offre liée) ou communs à l'opération, plus l'éventuelle
        valeur héritée de l'ancien modèle portée par la ligne elle-même.
        """
        if cost.cost_type not in self._PURCHASE_TYPES:
            return 0
        total = int(cost.tooling_included_pieces or 0)
        for t in self.costs.values():
            if t.cost_type != CostType.TOOLING:
                continue
            if t.linked_offer in (None, "") or t.linked_offer == cost.name:
                total += int(t.tooling_included_pieces or 0)
        return total

    def refresh_free_pieces(self) -> None:
        """Pose sur chaque ligne d'achat ses pièces gratuites (lu par Calculator)."""
        for c in self.costs.values():
            c._free_pieces = self.free_pieces_for(c) if c.cost_type in self._PURCHASE_TYPES else None

    def _tooling_retained(self, tool: CostItem) -> bool:
        """Un outillage rattaché à une offre non retenue n'est pas facturé."""
        if tool.linked_offer:
            offer = self.costs.get(tool.linked_offer)
            if offer is not None:
                return self._is_offer_retained(offer)
        return True

    def _tooling_billing(self, cost: CostItem) -> ToolingBilling:
        ctx = self.phase_ctx
        # Taux horaire (Lot) : outillage toujours refacturé, jamais amorti —
        # une surcharge « Amorti » (phase ou ligne) y est sans effet.
        if ctx is not None and ctx.kind == PhaseKind.LOT:
            return ToolingBilling.REINVOICED
        if cost.tooling_billing is not None:
            return cost.tooling_billing
        return ctx.tooling_billing if ctx else ToolingBilling.REINVOICED

    def _is_amortized_in_lot(self, cost: CostItem) -> bool:
        """Outillage amorti dans une phase LOT : réparti dans le prix pièce."""
        ctx = self.phase_ctx
        return (ctx is not None and ctx.kind == PhaseKind.LOT
                and self._tooling_billing(cost) == ToolingBilling.AMORTIZED)

    # ------------------------------------------------------------------ calculs

    def _get_active_costs(self):
        """Returns costs used in piece-price calculations (excludes reinvoiced tooling)."""
        priced = [c for c in self.costs.values() if c.cost_type != CostType.TOOLING]
        if self.typology == SUBCONTRACTING_TYPOLOGY:
            priced = [c for c in priced if c.is_active]
        # Outillage amorti en phase Lot : réparti sur la quantité commandée
        return priced + [t for t in self.get_tooling_costs() if self._is_amortized_in_lot(t)]

    def _is_offer_retained(self, cost: CostItem) -> bool:
        return self.typology != SUBCONTRACTING_TYPOLOGY or cost.is_active

    def get_tooling_costs(self):
        """Tooling of the current phase (all billing modes), incl. supplier tooling.

        L'outillage fournisseur d'une offre (Stüken…) est rendu sous forme de
        ligne virtuelle `supplier_tooling_item()` tant que l'offre est retenue.
        """
        tools = []
        for c in self.costs.values():
            if c.cost_type == CostType.TOOLING:
                if self._tooling_retained(c):
                    tools.append(c)
            elif c.has_supplier_tooling and self._is_offer_retained(c):
                tools.append(c.supplier_tooling_item())
        return tools

    def get_reinvoiced_tooling_costs(self):
        """Tooling lines billed separately (bloc OUTILLAGE de l'offre)."""
        return [c for c in self.get_tooling_costs()
                if self._tooling_billing(c) == ToolingBilling.REINVOICED]

    def get_amortized_tooling_costs(self):
        """Tooling lines amortized in the piece price."""
        return [c for c in self.get_tooling_costs()
                if self._tooling_billing(c) == ToolingBilling.AMORTIZED]

    def total_cost(self, quantity: int = None) -> float:
        """Calculate the unit base cost (aggregate of all cost items)"""
        q = quantity if quantity is not None else self.total_pieces
        from .calculator import Calculator
        self.refresh_free_pieces()
        return sum(Calculator.calculate_item(item, q).unit_cost_converted for item in self._get_active_costs())

    def total_with_margins(self, quantity: int = None) -> float:
        """Calculate the unit sale price (aggregate of all cost items with their margins)"""
        q = quantity if quantity is not None else self.total_pieces
        from .calculator import Calculator
        self.refresh_free_pieces()
        return sum(Calculator.calculate_item(item, q).unit_sale_price for item in self._get_active_costs())

    def calculate_sale_components(self, quantity: int = None) -> (float, float):
        """Calculate (fixed_total, variable_total) sale prices for the operation"""
        q = quantity if quantity is not None else self.total_pieces
        total_f = 0.0
        total_v = 0.0
        self.refresh_free_pieces()
        for item in self._get_active_costs():
            f, v = item.calculate_sale_components(q)
            total_f += f
            total_v += v
        return total_f, total_v

    def add_cost(self, name: str, cost_type: CostType, pricing_type: PricingType = PricingType.PER_UNIT, **kwargs):
        """Add a cost item with pricing structure"""
        pricing = PricingStructure(pricing_type=pricing_type, **kwargs)
        cost_item = CostItem(name=name, cost_type=cost_type, pricing=pricing, **kwargs)
        self.costs[name] = cost_item

    def update_cost(self, name: str, **kwargs):
        """Update cost item parameters"""
        if name in self.costs:
            for key, value in kwargs.items():
                if hasattr(self.costs[name], key):
                    setattr(self.costs[name], key, value)

    def move_cost(self, cost_name: str, direction: int) -> bool:
        """direction: -1 for up, 1 for down"""
        keys = list(self.costs.keys())
        try:
            idx = keys.index(cost_name)
            new_idx = idx + direction
            if 0 <= new_idx < len(keys):
                keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
                # Rebuild dict to preserve order
                new_costs = {k: self.costs[k] for k in keys}
                self.costs = new_costs
                return True
        except ValueError:
            pass
        return False

    def rename_cost(self, old_name: str, new_name: str) -> bool:
        """Safely rename a cost item and update the dictionary key while preserving order."""
        if old_name not in self.costs:
            return False
        if new_name == old_name:
            return True
        if new_name in self.costs or not new_name:
            return False

        # Rebuild dict to preserve order
        new_costs = {}
        for k, v in self.costs.items():
            if k == old_name:
                v.name = new_name
                new_costs[new_name] = v
            else:
                new_costs[k] = v
            if v.linked_offer == old_name:
                v.linked_offer = new_name  # les outillages rattachés suivent l'offre
        self.costs = new_costs
        self.refresh_free_pieces()
        return True
