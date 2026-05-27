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
from domain.serie_data import SerieData, CapexItem, ToolingItem, MachinePost

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

            # Process preview image if present
            project_preview = None
            if getattr(project, 'preview_image', None) and project.preview_image.filename and project.preview_image.data:
                preview_path = add_document(project.preview_image, "previews/")
                if preview_path:
                    project_preview = {'filename': project.preview_image.filename, '_path': preview_path}

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
            # Remove embedded binary content from project JSON (stored separately in ZIP)
            project_dict['documents'] = project_doc_paths
            project_dict['operations'] = ops_data
            project_dict['preview_image'] = project_preview
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

            # Load preview image
            preview_image = None
            preview_ref = data.get('preview_image')
            if preview_ref and preview_ref.get('_path'):
                preview_path = preview_ref.get('_path')
                if preview_path in zf.namelist():
                    binary_data = zf.read(preview_path)
                    preview_image = Document(
                        filename=preview_ref.get('filename'),
                        data=base64.b64encode(binary_data).decode('ascii')
                    )
                else:
                    preview_image = Document(filename=preview_ref.get('filename'), data=None)

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
                    template_id=op_data.get('template_id'),
                    template_name=op_data.get('template_name', ""),
                    template_snapshot=op_data.get('template_snapshot', {}) or {},
                    template_drift_score=op_data.get('template_drift_score', 0.0),
                    costs=costs,
                    total_pieces=op_data.get('total_pieces', 1)
                )
                operations.append(op)

            return Project(
                name=data['name'],
                reference=data.get('reference', ""),
                client=data.get('client', ""),
                mwq_uuid=data.get('mwq_uuid', ""),
                operations=operations,
                documents=proj_docs,
                project_date=data.get('project_date'),
                sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
                tags=data.get('tags', []),
                status=data.get('status', "En construction"),
                status_dates=data.get('status_dates', {}),
                export_history=data.get('export_history', []),
                volume_margin_rates=PersistenceService._migrate_volume_margins(data),
                preview_image=preview_image,
                validation_report=data.get('validation_report', {}) or {},
                serie_data=PersistenceService._load_serie_data(data.get('serie_data'))
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
            client_comment=cost_data.get('client_comment'),
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
                template_id=op_data.get('template_id'),
                template_name=op_data.get('template_name', ""),
                template_snapshot=op_data.get('template_snapshot', {}) or {},
                template_drift_score=op_data.get('template_drift_score', 0.0),
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
            mwq_uuid=data.get('mwq_uuid', ""),
            operations=operations,
            documents=proj_docs,
            project_date=data.get('project_date'),
            sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
            tags=data.get('tags', []),
            preview_image=None,
            status=data.get('status', "En construction"),
            status_dates=data.get('status_dates', {}),
            export_history=data.get('export_history', []),
            volume_margin_rates=PersistenceService._migrate_volume_margins(data),
            validation_report=data.get('validation_report', {}) or {},
            serie_data=PersistenceService._load_serie_data(data.get('serie_data'))
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
    def _load_serie_data(d) -> SerieData:
        """Reconstruit un SerieData depuis un dict JSON (ou None).

        Rétrocompatible : les anciens fichiers avec target_cycle_time_s sont
        migrés vers fallback_cycle_time_s.
        Les machine_posts sont rechargés mais seront re-synchronisés depuis
        les opérations du projet lors du chargement dans l'UI.
        """
        if not d:
            return None

        # Migration : target_cycle_time_s (ancien) → fallback_cycle_time_s
        fallback_tc = d.get('fallback_cycle_time_s', d.get('target_cycle_time_s', 0.0))

        # Reconstruction robuste des MachinePost (champs optionnels tolérés)
        raw_posts = d.get('machine_posts', [])
        posts = []
        for x in raw_posts:
            posts.append(MachinePost(
                operation_code=x.get('operation_code', ''),
                name=x.get('name', ''),
                cycle_time_s=x.get('cycle_time_s', 0.0),
                mo_rate_euro_per_h=x.get('mo_rate_euro_per_h', 0.0),
                machines_available=x.get('machines_available', 1),
            ))

        return SerieData(
            annual_volume=d.get('annual_volume', 100000),
            working_days_per_year=d.get('working_days_per_year', 220),
            shifts_per_day=d.get('shifts_per_day', 2),
            hours_per_shift=d.get('hours_per_shift', 7.0),
            trs=d.get('trs', 0.85),
            scrap_rate=d.get('scrap_rate', 0.0),
            program_lifetime_years=d.get('program_lifetime_years', 5),
            fallback_cycle_time_s=fallback_tc,
            mo_production_rate=d.get('mo_production_rate', 28.0),
            mo_quality_rate=d.get('mo_quality_rate', 28.0),
            overhead_coef=d.get('overhead_coef', 0.30),
            capex_items=[
                CapexItem(
                    name=x.get('name', 'CAPEX'),
                    cost=x.get('cost', 0.0),
                    residual_value=x.get('residual_value', 0.0),
                    margin_rate=x.get('margin_rate', 0.15),
                )
                for x in d.get('capex_items', [])
            ],
            capex_global_margin=d.get('capex_global_margin', 0.15),
            tooling_items=[ToolingItem(**x) for x in d.get('tooling_items', [])],
            machine_posts=posts,
            tooling_setup_time_h=d.get('tooling_setup_time_h', 1.0),
            sop_validation_time_h=d.get('sop_validation_time_h', 0.5),
            lot_size=d.get('lot_size', 5000),
            setup_margin=d.get('setup_margin', 0.15),
            spc_frequency=d.get('spc_frequency', 50),
            spc_time_per_piece_min=d.get('spc_time_per_piece_min', 2.0),
            control_100pct_time_s=d.get('control_100pct_time_s', 3.0),
            control_mode=d.get('control_mode', 'SPC'),
            material_cost_per_piece=d.get('material_cost_per_piece', 0.0),
            material_margin=d.get('material_margin', 0.10),
            logistics_cost_per_piece=d.get('logistics_cost_per_piece', 0.0),
            logistics_margin=d.get('logistics_margin', 0.05),
            global_commercial_margin=d.get('global_commercial_margin', 0.25),
        )

    @staticmethod
    def get_project_metadata(filepath: str) -> Tuple[Project, str]:
        """Load project and compute its content hash.

        Returns (project, content_hash) tuple.
        """
        project = PersistenceService.load_project(filepath)
        content_hash = PersistenceService.compute_content_hash(project)
        return project, content_hash
