
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from domain.project import Project
from domain.operation import Operation
from infrastructure.persistence import PersistenceService

def test_persistence():
    p = Project(name="Test Tags", reference="REF123", client="Client A")
    p.tags = ["Médical", "Prototype"]
    
    filepath = "test_tags.mwq"
    PersistenceService.save_project(p, filepath)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        print("JSON content:")
        print(f.read())
        
    p2 = PersistenceService.load_project(filepath)
    print(f"\nLoaded tags: {p2.tags}")
    
    if p2.tags == ["Médical", "Prototype"]:
        print("SUCCESS: Tags preserved")
    else:
        print("FAILURE: Tags lost")
    
    os.remove(filepath)

if __name__ == "__main__":
    test_persistence()
