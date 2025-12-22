# domain/pricing.py
from .project import Project

class PricingEngine:

    def compute(self, project: Project) -> float:
        # Ici viendront plus tard :
        # - marges
        # - coefficients
        # - règles conditionnelles
        return project.total_price()
