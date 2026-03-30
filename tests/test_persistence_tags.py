
import os
import sys
import base64

# Add current directory to path
sys.path.append(os.getcwd())

from domain.project import Project
from domain.document import Document
from domain.operation import Operation
from infrastructure.persistence import PersistenceService

def test_persistence():
    p = Project(name="Test Tags", reference="REF123", client="Client A")
    p.tags = ["Médical", "Prototype"]
    p.preview_image = Document(filename="preview.png", data=base64.b64encode(b"dummydata").decode('ascii'))

    filepath = "test_tags.mwq"
    PersistenceService.save_project(p, filepath)

    p2 = PersistenceService.load_project(filepath)

    assert p2.tags == ["Médical", "Prototype"]
    assert p2.preview_image is not None
    assert p2.preview_image.filename == "preview.png"
    assert p2.preview_image.data == p.preview_image.data

    os.remove(filepath)

if __name__ == "__main__":
    test_persistence()
