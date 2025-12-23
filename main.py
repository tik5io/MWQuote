#!/usr/bin/env python3
# main.py
import wx
from domain.project import Project
from domain.operation import Operation
from domain.cost import CostType, PricingType, PricingStructure, PricingTier, CostItem
from ui.main_frame import MainFrame


def create_sample_project():
    """Crée un projet d'exemple pour les tests"""
    project = Project(
        name="Projet Exemple",
        reference="PRJ-2024-001",
        client="Client Test"
    )
    
    # Opération 1 : Usinage
    op1 = Operation(code="USI", label="Usinage pièce", total_pieces=100)
    
    # Matière première avec tarification par échelons
    material_tiers = [
        PricingTier(min_quantity=1, max_quantity=50, unit_price=15.0, description="Prix standard"),
        PricingTier(min_quantity=51, max_quantity=200, unit_price=12.0, description="Remise 20%"),
        PricingTier(min_quantity=201, max_quantity=None, unit_price=10.0, description="Remise 33%")
    ]
    material_pricing = PricingStructure(
        pricing_type=PricingType.TIERED,
        tiers=material_tiers
    )
    material_cost = CostItem(
        name="Acier inox 316L",
        cost_type=CostType.MATERIAL,
        pricing=material_pricing,
        supplier_quote_ref="FOURNISSEUR-001",
        comment="Matière première"
    )
    op1.costs[material_cost.name] = material_cost
    
    # Opération interne
    machining_cost = CostItem(
        name="Temps d'usinage",
        cost_type=CostType.INTERNAL_OPERATION,
        pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
        fixed_time=2.0,
        per_piece_time=0.15,
        comment="Réglage + usinage"
    )
    op1.costs[machining_cost.name] = machining_cost
    
    # Marge
    margin_cost = CostItem(
        name="Marge commerciale",
        cost_type=CostType.MARGIN,
        pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
        margin_percentage=25.0,
        comment="Marge standard"
    )
    op1.costs[margin_cost.name] = margin_cost
    
    project.add_operation(op1)
    
    # Opération 2 : Traitement de surface
    op2 = Operation(code="TRT", label="Traitement de surface", total_pieces=100)
    
    # Sous-traitance avec prix forfaitaire
    subcontracting_pricing = PricingStructure(
        pricing_type=PricingType.PER_UNIT,
        fixed_price=500.0
    )
    subcontracting_cost = CostItem(
        name="Anodisation",
        cost_type=CostType.SUBCONTRACTING,
        pricing=subcontracting_pricing,
        supplier_quote_ref="ANODISEUR-42",
        comment="Traitement lot complet"
    )
    op2.costs[subcontracting_cost.name] = subcontracting_cost
    
    # Contrôle qualité
    qa_cost = CostItem(
        name="Contrôle qualité",
        cost_type=CostType.INTERNAL_OPERATION,
        pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
        fixed_time=1.0,
        per_piece_time=0.05,
        comment="Inspection visuelle et dimensionnelle"
    )
    op2.costs[qa_cost.name] = qa_cost
    
    # Marge
    margin2_cost = CostItem(
        name="Marge traitement",
        cost_type=CostType.MARGIN,
        pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
        margin_percentage=15.0,
        comment="Marge sur traitement"
    )
    op2.costs[margin2_cost.name] = margin2_cost
    
    project.add_operation(op2)
    
    return project


def main():
    """Point d'entrée de l'application"""
    app = wx.App()
    
    # Créer un projet d'exemple ou un projet vide
    project = create_sample_project()
    # project = None  # Pour démarrer avec un projet vide
    
    frame = MainFrame(project=project)
    
    app.MainLoop()


if __name__ == "__main__":
    main()