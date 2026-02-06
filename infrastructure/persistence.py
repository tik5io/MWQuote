# infrastructure/persistence.py
import json
import zipfile
import hashlib
import os
import base64
import dataclasses
from enum import Enum
from typing import Any, Dict, Tuple
from domain.project import Project
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingType, PricingStructure, PricingTier, ConversionType
from domain.document import Document

# Constants
PROJECT_JSON_FILENAME = "project.json"
DOCUMENTS_FOLDER = "documents/"
MWQ_VERSION = "2.0"  # ZIP format version


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


class PersistenceService:
    """Service for saving and loading .mwq project files.

    Format v2.0: ZIP archive containing:
      - project.json: Project metadata and structure (documents stored as references)
      - documents/: Folder containing actual document files

    Backward compatible with v1.0 (plain JSON with embedded base64 documents).
    """

    @staticmethod
    def is_zip_format(filepath: str) -> bool:
        """Check if file is ZIP format (v2.0) or legacy JSON (v1.0)."""
        try:
            with open(filepath, 'rb') as f:
                # ZIP files start with PK (0x50, 0x4B)
                magic = f.read(2)
                return magic == b'PK'
        except:
            return False

    @staticmethod
    def compute_content_hash(project: Project) -> str:
        """Compute a stable hash for project identification.

        Uses reference + client + name as identity key.
        This allows reconnecting moved files.
        """
        identity = f"{project.reference}|{project.client}|{project.name}"
        return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def project_to_json(project: Project) -> str:
        """Serialize project to JSON string."""
        return json.dumps(project, cls=EnhancedJSONEncoder, indent=2, ensure_ascii=False)

    @staticmethod
    def save_project(project: Project, filepath: str):
        """Save project to ZIP-based .mwq file."""
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Collect all documents with unique names
            doc_index = {}  # path -> data
            doc_counter = {}  # base_filename -> counter for uniqueness

            def add_document(doc: Document, prefix: str = "") -> str:
                """Add document to index, return unique path."""
                if not doc.filename or not doc.data:
                    return None

                base_name = doc.filename
                if base_name in doc_counter:
                    doc_counter[base_name] += 1
                    name, ext = os.path.splitext(base_name)
                    unique_name = f"{name}_{doc_counter[base_name]}{ext}"
                else:
                    doc_counter[base_name] = 0
                    unique_name = base_name

                unique_path = f"{DOCUMENTS_FOLDER}{prefix}{unique_name}"
                doc_index[unique_path] = doc.data
                return unique_path

            # Process project documents
            project_doc_paths = []
            for doc in project.documents:
                path = add_document(doc, "project/")
                if path:
                    project_doc_paths.append({'filename': doc.filename, '_path': path})

            # Process operation cost documents
            ops_data = []
            for op in project.operations:
                op_dict = dataclasses.asdict(op)
                for cost_name, cost_data in op_dict.get('costs', {}).items():
                    cost_obj = op.costs.get(cost_name)
                    if cost_obj and cost_obj.documents:
                        cost_doc_paths = []
                        for doc in cost_obj.documents:
                            path = add_document(doc, f"costs/{op.code}/")
                            if path:
                                cost_doc_paths.append({'filename': doc.filename, '_path': path})
                        cost_data['documents'] = cost_doc_paths
                ops_data.append(op_dict)

            # Build project JSON (without embedded data)
            project_dict = dataclasses.asdict(project)
            project_dict['documents'] = project_doc_paths
            project_dict['operations'] = ops_data
            project_dict['_mwq_version'] = MWQ_VERSION
            project_dict['_content_hash'] = PersistenceService.compute_content_hash(project)

            # Write project.json
            json_content = json.dumps(project_dict, cls=EnhancedJSONEncoder, indent=2, ensure_ascii=False)
            zf.writestr(PROJECT_JSON_FILENAME, json_content.encode('utf-8'))

            # Write documents
            for doc_path, doc_data in doc_index.items():
                try:
                    binary_data = base64.b64decode(doc_data)
                    zf.writestr(doc_path, binary_data)
                except Exception as e:
                    print(f"Warning: Could not write document {doc_path}: {e}")

    @staticmethod
    def load_project(filepath: str) -> Project:
        """Load project from .mwq file (ZIP v2.0 or legacy JSON v1.0)."""
        if PersistenceService.is_zip_format(filepath):
            return PersistenceService._load_project_zip(filepath)
        else:
            return PersistenceService._load_project_legacy(filepath)

    @staticmethod
    def _load_project_zip(filepath: str) -> Project:
        """Load project from ZIP format."""
        with zipfile.ZipFile(filepath, 'r') as zf:
            # Read project.json
            json_content = zf.read(PROJECT_JSON_FILENAME).decode('utf-8')
            data = json.loads(json_content)

            # Load project documents
            proj_docs = []
            for doc_ref in data.get('documents', []):
                doc_path = doc_ref.get('_path')
                if doc_path and doc_path in zf.namelist():
                    binary_data = zf.read(doc_path)
                    proj_docs.append(Document(
                        filename=doc_ref['filename'],
                        data=base64.b64encode(binary_data).decode('ascii')
                    ))
                elif doc_ref.get('filename'):
                    # Reference exists but file missing - keep reference with no data
                    proj_docs.append(Document(filename=doc_ref['filename'], data=None))

            # Load operations with their documents
            operations = []
            for op_data in data.get('operations', []):
                costs = {}
                for cost_name, cost_data in op_data.get('costs', {}).items():
                    # Load cost documents
                    docs = []
                    for doc_ref in cost_data.get('documents', []):
                        doc_path = doc_ref.get('_path')
                        if doc_path and doc_path in zf.namelist():
                            binary_data = zf.read(doc_path)
                            docs.append(Document(
                                filename=doc_ref['filename'],
                                data=base64.b64encode(binary_data).decode('ascii')
                            ))
                        elif doc_ref.get('filename'):
                            docs.append(Document(filename=doc_ref['filename'], data=None))

                    # Build cost item
                    cost = PersistenceService._build_cost_item(cost_data, docs)
                    if cost:
                        costs[cost_name] = cost

                op = Operation(
                    code=op_data['code'],
                    label=op_data['label'],
                    typology=op_data.get('typology', ""),
                    comment=op_data.get('comment', ""),
                    costs=costs,
                    total_pieces=op_data.get('total_pieces', 1)
                )
                operations.append(op)

            return Project(
                name=data['name'],
                reference=data.get('reference', ""),
                client=data.get('client', ""),
                operations=operations,
                documents=proj_docs,
                project_date=data.get('project_date'),
                sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
                tags=data.get('tags', []),
                status=data.get('status', "En construction"),
                status_dates=data.get('status_dates', {}),
                export_history=data.get('export_history', []),
                volume_margin_rates=PersistenceService._migrate_volume_margins(data)
            )

    @staticmethod
    def _load_project_legacy(filepath: str) -> Project:
        """Load project from legacy JSON format (v1.0)."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return PersistenceService.project_from_dict(data)

    @staticmethod
    def _build_cost_item(cost_data: Dict, docs: list) -> CostItem:
        """Build a CostItem from dict data."""
        ctype_val = cost_data.get('cost_type')
        if ctype_val == "Marge":
            return None  # Skip legacy margin items

        # Reconstruct PricingStructure
        p_data = cost_data.get('pricing', {})
        tiers = []
        for t_data in p_data.get('tiers', []):
            tiers.append(PricingTier(
                min_quantity=t_data['min_quantity'],
                unit_price=t_data.get('unit_price', 0.0),
                description=t_data.get('description', "")
            ))

        pricing = PricingStructure(
            pricing_type=PricingType(p_data['pricing_type']),
            fixed_price=p_data.get('fixed_price', 0.0),
            unit_price=p_data.get('unit_price', 0.0),
            unit=p_data.get('unit', "pièce"),
            tiers=tiers
        )

        return CostItem(
            name=cost_data['name'],
            cost_type=CostType(ctype_val),
            pricing=pricing,
            supplier_quote_ref=cost_data.get('supplier_quote_ref'),
            documents=docs,
            comment=cost_data.get('comment'),
            fixed_time=cost_data.get('fixed_time', 0.0),
            per_piece_time=cost_data.get('per_piece_time', 0.0),
            hourly_rate=cost_data.get('hourly_rate', 0.0),
            margin_rate=cost_data.get('margin_rate', cost_data.get('margin_percentage', 0.0)),
            conversion_factor=cost_data.get('conversion_factor', cost_data.get('quantity_multiplier', 1.0)),
            conversion_type=ConversionType(cost_data.get('conversion_type', "Multiplier")),
            quantity_per_piece=cost_data.get('quantity_per_piece', 1.0),
            quantity_per_piece_is_inverse=cost_data.get('quantity_per_piece_is_inverse', False),
            is_active=cost_data.get('is_active', True)
        )

    @staticmethod
    def project_from_dict(data: Dict[str, Any]) -> Project:
        """Reconstruct Project from dictionary (legacy format)."""
        operations = []
        for op_data in data.get('operations', []):
            costs = {}
            for cost_name, cost_data in op_data.get('costs', {}).items():
                # Documents migration/reconstruction
                docs = []
                for d_data in cost_data.get('documents', []):
                    docs.append(Document(filename=d_data['filename'], data=d_data.get('data')))

                # Backward compatibility migration
                if not docs and cost_data.get('supplier_quote_filename') and cost_data.get('supplier_quote_data'):
                    docs.append(Document(
                        filename=cost_data['supplier_quote_filename'],
                        data=cost_data['supplier_quote_data']
                    ))

                cost = PersistenceService._build_cost_item(cost_data, docs)
                if cost:
                    costs[cost_name] = cost

            op = Operation(
                code=op_data['code'],
                label=op_data['label'],
                typology=op_data.get('typology', ""),
                comment=op_data.get('comment', ""),
                costs=costs,
                total_pieces=op_data.get('total_pieces', 1)
            )
            operations.append(op)

        # Project Documents migration/reconstruction
        proj_docs = []
        for d_data in data.get('documents', []):
            proj_docs.append(Document(filename=d_data['filename'], data=d_data.get('data')))

        # Backward compatibility
        if not proj_docs and data.get('drawing_filename') and data.get('drawing_data'):
            proj_docs.append(Document(
                filename=data['drawing_filename'],
                data=data['drawing_data']
            ))

        return Project(
            name=data['name'],
            reference=data.get('reference', ""),
            client=data.get('client', ""),
            operations=operations,
            documents=proj_docs,
            project_date=data.get('project_date'),
            sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
            tags=data.get('tags', []),
            status=data.get('status', "En construction"),
            status_dates=data.get('status_dates', {}),
            export_history=data.get('export_history', []),
            volume_margin_rates=PersistenceService._migrate_volume_margins(data)
        )

    @staticmethod
    def migrate_to_zip(filepath: str) -> bool:
        """Migrate a legacy JSON .mwq file to ZIP format.

        Returns True if migration was performed, False if already ZIP or error.
        """
        if PersistenceService.is_zip_format(filepath):
            return False  # Already ZIP format

        try:
            project = PersistenceService._load_project_legacy(filepath)
            # Save in new format (overwrites)
            PersistenceService.save_project(project, filepath)
            return True
        except Exception as e:
            print(f"Migration error for {filepath}: {e}")
            return False

    @staticmethod
    def _migrate_volume_margins(data: dict) -> dict:
        """Helper to migrate from volume_margin_rate to volume_margin_rates."""
        rates = data.get('volume_margin_rates', {})
        # If rates is empty or not present, but old rate is present, migrate it
        if not rates and 'volume_margin_rate' in data:
            old_rate = data['volume_margin_rate']
            qtys = data.get('sale_quantities', [1, 10, 50, 100])
            rates = {str(q): old_rate for q in qtys}
        
        # Ensure keys are strings for JSON compatibility if they came from elsewhere
        # but normalize to int keys in the domain if possible. 
        # Actually, dict keys in JSON must be strings.
        # In the Domain model, we use quantities as keys.
        return {int(k): float(v) for k, v in rates.items()}

    @staticmethod
    def get_project_metadata(filepath: str) -> Tuple[Project, str]:
        """Load project and compute its content hash.

        Returns (project, content_hash) tuple.
        """
        project = PersistenceService.load_project(filepath)
        content_hash = PersistenceService.compute_content_hash(project)
        return project, content_hash
