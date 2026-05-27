# domain/serie_data.py
from dataclasses import dataclass, field
from typing import List


@dataclass
class CapexItem:
    name: str = "CAPEX"
    cost: float = 0.0
    residual_value: float = 0.0
    margin_rate: float = 0.15


@dataclass
class ToolingItem:
    name: str = "Outillage"
    cost: float = 0.0
    lifetime_pieces: int = 100000
    margin_rate: float = 0.20


@dataclass
class MachinePost:
    """Poste machine lié à une Opération du projet.

    cycle_time_s et mo_rate_euro_per_h sont toujours recalculés
    via SerieData.sync_from_project() — ne pas les modifier manuellement.
    Seul machines_available est éditable par l'utilisateur.
    """
    operation_code: str = ""          # clé → Operation.code
    name: str = ""                    # libellé affiché (= op.label)
    cycle_time_s: float = 0.0        # Σ per_piece_time (h) × 3600 des coûts INTERNAL
    mo_rate_euro_per_h: float = 0.0  # TH moyen pondéré de l'opération
    machines_available: int = 1       # éditable dans l'onglet Série


@dataclass
class SerieData:
    """Données de chiffrage production grande série.

    Les postes machines (machine_posts) sont toujours synchronisés
    depuis les Opérations du projet via sync_from_project().
    Les temps de cycle et TH ne sont jamais saisis manuellement ici.
    """
    # ---- Hypothèses générales ----
    annual_volume: int = 100000
    working_days_per_year: int = 220
    shifts_per_day: int = 2
    hours_per_shift: float = 7.0
    trs: float = 0.85

    # ---- Rebut & programme ----
    scrap_rate: float = 0.0              # taux de rebut interne (ex: 0.02 = 2 %)
    program_lifetime_years: int = 5      # durée totale du programme (ans)

    # TC de secours : utilisé uniquement si le projet n'a aucune opération interne
    fallback_cycle_time_s: float = 0.0

    # ---- Taux horaires (pour setup, contrôle, fallback MO) ----
    mo_production_rate: float = 28.0    # €/h (setup + fallback MO)
    mo_quality_rate: float = 28.0       # €/h (contrôle)
    overhead_coef: float = 0.0          # surcoût structure sur TC×TH (0 si TH déjà chargé)

    # ---- CAPEX ----
    capex_items: List[CapexItem] = field(default_factory=list)
    capex_global_margin: float = 0.15

    # ---- Tooling ----
    tooling_items: List[ToolingItem] = field(default_factory=list)

    # ---- Postes machine (synchronisés depuis les Opérations) ----
    machine_posts: List[MachinePost] = field(default_factory=list)

    # ---- Setup ----
    tooling_setup_time_h: float = 1.0
    sop_validation_time_h: float = 0.5
    lot_size: int = 5000
    setup_margin: float = 0.15

    # ---- Contrôle qualité ----
    spc_frequency: int = 50             # 1 pièce / N
    spc_time_per_piece_min: float = 2.0
    control_100pct_time_s: float = 3.0
    control_mode: str = "SPC"           # "SPC" ou "100%"

    # ---- Coûts manuels (achats, logistique) ----
    material_cost_per_piece: float = 0.0
    material_margin: float = 0.10
    logistics_cost_per_piece: float = 0.0
    logistics_margin: float = 0.05

    # ---- Marge commerciale globale ----
    global_commercial_margin: float = 0.25

    # ================================================================
    # Synchronisation avec le projet
    # ================================================================

    def sync_from_project(self, project) -> None:
        """Re-dérive les postes machines depuis les Opérations du projet.

        Seules les opérations NON sous-traitées sont incluses.
        Préserve machines_available existant par operation_code.
        TC = Σ per_piece_time (h) des coûts INTERNAL_OPERATION × 3600.
        TH = moyenne pondérée par temps des TH des mêmes coûts.
        """
        from domain.cost import CostType
        from domain.operation import SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY

        old_machines = {p.operation_code: p.machines_available for p in self.machine_posts}
        self.machine_posts = []

        for op in project.operations:
            if op.typology in (SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY):
                continue
            tc_h = 0.0
            rate_x_time = 0.0

            for cost in op.costs.values():
                if cost.cost_type == CostType.INTERNAL_OPERATION and getattr(cost, 'is_active', True):
                    tc_h += cost.per_piece_time
                    rate_x_time += cost.per_piece_time * cost.hourly_rate

            # Inclure l'opération même si TC = 0 (pour info), sauf si aucun coût interne du tout
            avg_rate = (rate_x_time / tc_h) if tc_h > 0 else self.mo_production_rate

            self.machine_posts.append(MachinePost(
                operation_code=op.code,
                name=op.label,
                cycle_time_s=tc_h * 3600.0,
                mo_rate_euro_per_h=avg_rate,
                machines_available=old_machines.get(op.code, 1),
            ))

    # ================================================================
    # Rebut
    # ================================================================

    def scrap_factor(self) -> float:
        """Facteur rebut : coût réel / pièce livrée = coût_cycle × scrap_factor.
        À 2 % de rebut → scrap_factor = 1 / 0.98 ≈ 1.0204.
        """
        if self.scrap_rate <= 0 or self.scrap_rate >= 1.0:
            return 1.0
        return 1.0 / (1.0 - self.scrap_rate)

    def production_volume_per_year(self) -> float:
        """Volume produit réel (livraisons + rebuts)."""
        return self.annual_volume * self.scrap_factor()

    def scrap_units_per_year(self) -> float:
        return self.production_volume_per_year() - self.annual_volume

    # ================================================================
    # Life of Program
    # ================================================================

    def total_program_volume(self) -> int:
        """Volume total livré sur la durée du programme."""
        return int(self.annual_volume * self.program_lifetime_years)

    def total_program_revenue(self) -> float:
        return self.selling_price_per_piece() * self.total_program_volume()

    def total_program_cost(self) -> float:
        return self.total_cost_per_piece() * self.total_program_volume()

    def total_capex_net_investment(self) -> float:
        """Investissement CAPEX net total (coût - résiduel) — constant quelle que soit la durée.

        Dans total_program_cost(), la contribution CAPEX = capex_cost_per_piece × total_volume
        = (total_capex_net / years / volume) × volume × years = total_capex_net.
        Ce montant ne change pas si on allonge le programme.
        """
        return sum(item.cost - item.residual_value for item in self.capex_items)

    def total_tooling_investment(self) -> float:
        """Investissement tooling total (coût brut, indépendant de la durée du programme).

        Le tooling est un achat one-shot : son coût total ne dépend pas du nombre d'années.
        Remarque : si total_program_volume > lifetime_pieces, l'outil doit être renouvelé
        (le coût réel serait alors supérieur).
        """
        return sum(item.cost for item in self.tooling_items)

    def total_fixed_investment(self) -> float:
        """Total des investissements one-shot (CAPEX net + Tooling)."""
        return self.total_capex_net_investment() + self.total_tooling_investment()

    def total_variable_program_cost(self) -> float:
        """Coûts de production variables sur la durée du programme (hors CAPEX et Tooling).

        = (MO + setup + contrôle + matières + logistique) / pièce × volume_total_livré
        Croît proportionnellement au volume produit.
        """
        # Contribution tooling dans total_program_cost = tooling_cost_per_piece × total_volume
        # = (Σcost / lifetime_pieces) × volume × years  ← peut différer du coût réel outil
        # On utilise total_tooling_investment() pour représenter le vrai achat one-shot.
        tooling_contribution_in_cost = self.tooling_cost_per_piece() * self.total_program_volume()
        return (self.total_program_cost()
                - self.total_capex_net_investment()
                - tooling_contribution_in_cost)

    # ================================================================
    # TC & capacité
    # ================================================================

    def get_target_cycle_time_s(self) -> float:
        """Goulot = max(TC_post / machines) des postes actifs.
        Fallback sur fallback_cycle_time_s si aucun poste n'a de TC.
        """
        times = [
            p.cycle_time_s / p.machines_available
            for p in self.machine_posts
            if p.cycle_time_s > 0 and p.machines_available > 0
        ]
        return max(times) if times else self.fallback_cycle_time_s

    def capacity_per_shift(self) -> float:
        tc = self.get_target_cycle_time_s()
        if tc <= 0:
            return 0.0
        return self.hours_per_shift * 3600.0 / tc

    def real_capacity_per_shift(self) -> float:
        return self.capacity_per_shift() * self.trs

    def real_capacity_per_year(self) -> float:
        return self.real_capacity_per_shift() * self.shifts_per_day * self.working_days_per_year

    def load_rate(self) -> float:
        """Taux de charge basé sur le volume de production réel (inclut les rebuts)."""
        cap = self.real_capacity_per_year()
        return (self.production_volume_per_year() / cap) if cap > 0 else 0.0

    # ================================================================
    # MO directe — utilise le détail des opérations
    # ================================================================

    def mo_cost_per_piece(self) -> float:
        """MO directe / pièce LIVRÉE = Σ postes (TC/3600 × TH × (1+overhead)) × scrap_factor.

        Le scrap_factor compense les cycles supplémentaires sur les pièces rebutées.
        """
        active = [p for p in self.machine_posts if p.cycle_time_s > 0]
        if active:
            base = sum(
                (p.cycle_time_s / 3600.0) * p.mo_rate_euro_per_h * (1.0 + self.overhead_coef)
                for p in active
            )
        else:
            tc = self.fallback_cycle_time_s
            base = (tc / 3600.0) * self.mo_production_rate * (1.0 + self.overhead_coef) if tc > 0 else 0.0
        return base * self.scrap_factor()

    # ================================================================
    # CAPEX
    # ================================================================

    def annual_capex_amortization(self) -> float:
        if self.program_lifetime_years <= 0:
            return 0.0
        return sum(item.cost - item.residual_value for item in self.capex_items) / self.program_lifetime_years

    def capex_cost_per_piece(self) -> float:
        if self.annual_volume <= 0:
            return 0.0
        return self.annual_capex_amortization() / self.annual_volume

    def capex_price_per_piece(self) -> float:
        return self.capex_cost_per_piece() * (1.0 + self.capex_global_margin)

    # ================================================================
    # Tooling
    # ================================================================

    def tooling_cost_per_piece(self) -> float:
        return sum(
            (item.cost / item.lifetime_pieces) if item.lifetime_pieces > 0 else 0.0
            for item in self.tooling_items
        )

    def tooling_price_per_piece(self) -> float:
        return sum(
            (item.cost / item.lifetime_pieces) * (1.0 + item.margin_rate)
            if item.lifetime_pieces > 0 else 0.0
            for item in self.tooling_items
        )

    # ================================================================
    # Setup
    # ================================================================

    def setup_time_total_h(self) -> float:
        return self.tooling_setup_time_h + self.sop_validation_time_h

    def campaigns_per_year(self) -> float:
        return (self.annual_volume / self.lot_size) if self.lot_size > 0 else 0.0

    def setup_cost_per_campaign(self) -> float:
        return self.setup_time_total_h() * self.mo_production_rate

    def setup_cost_per_year(self) -> float:
        return self.campaigns_per_year() * self.setup_cost_per_campaign()

    def setup_cost_per_piece(self) -> float:
        if self.annual_volume <= 0:
            return 0.0
        return self.setup_cost_per_year() / self.annual_volume

    def setup_price_per_piece(self) -> float:
        return self.setup_cost_per_piece() * (1.0 + self.setup_margin)

    # ================================================================
    # Contrôle
    # ================================================================

    def spc_cost_per_piece(self) -> float:
        if self.spc_frequency <= 0:
            return 0.0
        cost_per_measured = (self.spc_time_per_piece_min / 60.0) * self.mo_quality_rate
        return cost_per_measured / self.spc_frequency

    def control_100pct_cost_per_piece(self) -> float:
        return (self.control_100pct_time_s / 3600.0) * self.mo_quality_rate

    def control_cost_per_piece(self) -> float:
        return self.control_100pct_cost_per_piece() if self.control_mode == "100%" else self.spc_cost_per_piece()

    # ================================================================
    # Synthèse
    # ================================================================

    def total_cost_per_piece(self) -> float:
        sf = self.scrap_factor()
        return (
            self.mo_cost_per_piece()                             # scrap déjà inclus
            + self.capex_cost_per_piece()
            + self.tooling_cost_per_piece()
            + self.setup_cost_per_piece()
            + self.control_cost_per_piece()
            + self.material_cost_per_piece * sf                  # matière consommée sur pièces rebutées
            + self.logistics_cost_per_piece                      # logistique = pièces livrées seulement
        )

    def subtotal_with_item_margins(self) -> float:
        """Prix client avant marge commerciale (marges propres à chaque poste appliquées)."""
        sf = self.scrap_factor()
        return (
            self.mo_cost_per_piece()                                                        # overhead + scrap inclus
            + self.capex_price_per_piece()
            + self.tooling_price_per_piece()
            + self.setup_price_per_piece()
            + self.control_cost_per_piece()
            + self.material_cost_per_piece * sf * (1.0 + self.material_margin)             # scrap sur matière
            + self.logistics_cost_per_piece * (1.0 + self.logistics_margin)                # livré uniquement
        )

    def selling_price_per_piece(self) -> float:
        return self.subtotal_with_item_margins() * (1.0 + self.global_commercial_margin)

    def annual_revenue(self) -> float:
        return self.selling_price_per_piece() * self.annual_volume
