
import os
import random
import string
import datetime
from domain.project import Project
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingStructure, PricingType
from infrastructure.persistence import PersistenceService

def generate_reference():
    # Format: OPP-YY-XXXXXX-XXXX
    year = 25
    seq = random.randint(1000, 9999)
    sub = random.randint(1000, 9999)
    return f"OPP-{year}-{seq}-{sub}"

def generate_random_cost(name):
    cost_type = random.choice(list(CostType))
    pricing = PricingStructure(pricing_type=PricingType.PER_UNIT, unit_price=random.uniform(1.0, 100.0))
    return CostItem(
        name=name,
        cost_type=cost_type,
        pricing=pricing,
        fixed_time=random.uniform(0.1, 2.0),
        per_piece_time=random.uniform(0.01, 0.5),
        hourly_rate=random.uniform(50.0, 200.0)
    )

def generate_project(i):
    clients = ["MINITUBES", "MEDTRONIC", "EDWARDS", "ABBOTT", "BOSTON SCIENTIFIC"]
    client = random.choice(clients)
    name = f"Projet Test {i}"
    reference = generate_reference()
    
    ops = []
    op_codes = ["Microdécoupe", "Soudage", "Contrôle", "Nettoyage", "Emballage"]
    
    for j in range(random.randint(2, 5)):
        code = random.choice(op_codes)
        op = Operation(
            code=code,
            label=f"Operation {j+1}: {code}",
            total_pieces=1
        )
        # Add some costs
        op.costs["Cost1"] = generate_random_cost("Setup")
        op.costs["Cost2"] = generate_random_cost("Run")
        ops.append(op)
        
    project = Project(
        name=name,
        reference=reference,
        client=client,
        operations=ops,
        sale_quantities=[1, 10, 50, 100, 500, 1000],
        tags=["test", "generated", client.lower()]
    )
    return project

def main():
    output_dir = "TestFiles"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"Generating 20 test projects in {output_dir}...")
    
    for i in range(20):
        project = generate_project(i)
        filename = f"{project.client}_{project.reference}.mwq"
        filepath = os.path.join(output_dir, filename)
        PersistenceService.save_project(project, filepath)
        print(f"Generated {filepath}")
        
    print("Done.")

if __name__ == "__main__":
    main()
