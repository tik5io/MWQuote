from dataclasses import dataclass

@dataclass
class Document:
    filename: str
    data: str  # Base64 string
