# domain/calculator.py
from dataclasses import dataclass
from typing import Dict, Any, List
from .cost import CostItem, CostType, PricingType, ConversionType

@dataclass
class CalculationResult:
    """Detailed breakdown of a cost calculation for transparency."""
    production_qty: int
    unit_consumption: float
    quote_qty_needed: float
    moq: float
    quote_qty_ordered: float
    
    # Supplier side (Batch)
    supplier_unit_price: float
    supplier_fixed_price: float
    batch_supplier_cost: float
    
    # Internal side (Per piece)
    unit_cost_brut: float
    unit_cost_converted: float
    unit_sale_price: float
    
    # Components for graph
    fixed_part: float  # Per piece
    variable_part: float # Per piece
    
    margin_rate: float
    conversion_factor: float
    conversion_type: ConversionType

class Calculator:
    """Central engine for all cost and price calculations."""
    
    @staticmethod
    def calculate_item(cost_item: CostItem, total_pieces: int) -> CalculationResult:
        if total_pieces <= 0:
            return Calculator._empty_result(total_pieces, cost_item)

        # 1. Quantities
        unit_consumption = cost_item.quantity_per_piece if cost_item.quantity_per_piece is not None else 1.0
        quote_qty_needed = total_pieces * unit_consumption
        
        moq = cost_item.get_moq()
        quote_qty_ordered = max(quote_qty_needed, moq) if cost_item.cost_type == CostType.SUBCONTRACTING else quote_qty_needed

        # 2. Supplier Batch Pricing
        if cost_item.cost_type == CostType.INTERNAL_OPERATION and not (cost_item.pricing and (cost_item.pricing.unit_price != 0 or cost_item.pricing.fixed_price != 0 or cost_item.pricing.tiers)):
            # Special case for legacy time-based internal operation
            total_time = cost_item.fixed_time + (cost_item.per_piece_time * total_pieces)
            batch_supplier_cost = total_time * cost_item.hourly_rate
            supplier_unit_price = cost_item.hourly_rate
            supplier_fixed_price = 0.0 # Time-based is mixed
            f_batch = cost_item.fixed_time * cost_item.hourly_rate
            v_batch = cost_item.per_piece_time * total_pieces * cost_item.hourly_rate
        else:
            # Standard PricingStructure usage
            batch_supplier_cost = cost_item.pricing.calculate_price(quote_qty_ordered)
            f_batch, v_batch = cost_item.pricing.calculate_components(quote_qty_ordered)
            
            # Extract unit price from tier/structure for documentation
            tier = cost_item.pricing.get_applicable_tier(quote_qty_ordered) if cost_item.pricing.pricing_type == PricingType.TIERED else None
            supplier_unit_price = tier.unit_price if tier else cost_item.pricing.unit_price
            supplier_fixed_price = cost_item.pricing.fixed_price

        # 3. Unit Cost Bruts (Per produced piece)
        unit_cost_brut = batch_supplier_cost / total_pieces
        fixed_part_brut = f_batch / total_pieces
        variable_part_brut = v_batch / total_pieces

        # 4. Conversion & Margin
        conv_factor = cost_item.conversion_factor if cost_item.conversion_factor != 0 else 1.0
        if cost_item.conversion_type == ConversionType.DIVIDE:
            unit_cost_converted = unit_cost_brut / conv_factor
            unit_f = fixed_part_brut / conv_factor
            unit_v = variable_part_brut / conv_factor
        else:
            unit_cost_converted = unit_cost_brut * conv_factor
            unit_f = fixed_part_brut * conv_factor
            unit_v = variable_part_brut * conv_factor

        m_rate = min(cost_item.margin_rate, 99.9)
        m_factor = 1.0 / (1.0 - m_rate / 100.0)
        unit_sale_price = unit_cost_converted * m_factor

        return CalculationResult(
            production_qty=total_pieces,
            unit_consumption=unit_consumption,
            quote_qty_needed=quote_qty_needed,
            moq=moq,
            quote_qty_ordered=quote_qty_ordered,
            supplier_unit_price=supplier_unit_price,
            supplier_fixed_price=supplier_fixed_price,
            batch_supplier_cost=batch_supplier_cost,
            unit_cost_brut=unit_cost_brut,
            unit_cost_converted=unit_cost_converted,
            unit_sale_price=unit_sale_price,
            fixed_part=unit_f * m_factor,
            variable_part=unit_v * m_factor,
            margin_rate=cost_item.margin_rate,
            conversion_factor=conv_factor,
            conversion_type=cost_item.conversion_type
        )

    @staticmethod
    def _empty_result(qty: int, item: CostItem) -> CalculationResult:
        return CalculationResult(
            production_qty=qty, unit_consumption=1.0, quote_qty_needed=0, moq=0, quote_qty_ordered=0,
            supplier_unit_price=0, supplier_fixed_price=0, batch_supplier_cost=0,
            unit_cost_brut=0, unit_cost_converted=0, unit_sale_price=0,
            fixed_part=0, variable_part=0,
            margin_rate=item.margin_rate, conversion_factor=item.conversion_factor, conversion_type=item.conversion_type
        )
