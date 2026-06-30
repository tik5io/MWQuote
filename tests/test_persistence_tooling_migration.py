import unittest
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingStructure, PricingType
from infrastructure.persistence import PersistenceService

class PersistenceToolingMigrationTest(unittest.TestCase):
    def test_migrate_tooling_operations_in_ops_attaches_to_previous(self):
        # Create a regular op then a tooling op
        op1 = Operation(code='OP1', label='Op1', typology='Mécanique')
        op2 = Operation(code='OP2', label='Tooling', typology='OUTILLAGE')
        pricing = PricingStructure(PricingType.PER_UNIT)
        c = CostItem(name='T1', cost_type=CostType.TOOLING, pricing=pricing)
        op2.costs['T1'] = c
        ops = [op1, op2]

        migrated = PersistenceService._migrate_tooling_operations_in_ops(ops)
        self.assertEqual(len(migrated), 1)
        self.assertIn('T1', migrated[0].costs)
        self.assertEqual(migrated[0].costs['T1'].cost_type, CostType.TOOLING)

    def test_migrate_tooling_operations_attaches_to_last_when_at_end(self):
        op1 = Operation(code='OP1', label='Op1', typology='Mécanique')
        op2 = Operation(code='OP2', label='Tooling', typology='OUTILLAGE')
        pricing = PricingStructure(PricingType.PER_UNIT)
        c = CostItem(name='T1', cost_type=CostType.TOOLING, pricing=pricing)
        op2.costs['T1'] = c
        ops = [op1, op2]

        migrated = PersistenceService._migrate_tooling_operations_in_ops(ops)
        self.assertEqual(len(migrated), 1)
        self.assertIn('T1', migrated[0].costs)

if __name__ == '__main__':
    unittest.main()
