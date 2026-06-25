# infrastructure/persistence.py
import json
import zipfile
import hashlib
import os
import base64
import dataclasses
from enum import Enum
from typing import Any, Dict, List, Tuple
from domain.project import Project
from domain.project_version import ProjectVersion
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingType, PricingStructure, PricingTier, ConversionType
from domain.document import Document
from domain.serie_data import SerieData, CapexItem, ToolingItem, MachinePost

# Constants
PROJECT_JSON_FILENAME = "project.json"
DOCUMENTS_FOLDER = "documents/"
MWQ_VERSION = "3.0"  # Versioned project format


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


class PersistenceService:
    """Service for saving and loading .mwq project files.

    Format v3.0: ZIP archive with versioned project structure.
    Format v2.0: ZIP archive (single-version, backward compatible).
    Format v1.0: Plain JSON (legacy, backward compatible).
    """

    @staticmethod
    def is_zip_format(filepath: str) -> bool:
        try:
            with open(filepath, 'rb') as f:
                magic = f.read(2)
                return magic == b'PK'
        except:
            return False

    @staticmethod
    def compute_content_hash(project: Project) -> str:
        identity = f"{project.reference}|{project.client}|{project.name}"
        return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def save_project(project: Project, filepath: str):
        """Save project to ZIP-based .mwq file (v3.0 format)."""
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
            doc_index = {}   # path -> base64 data
            doc_counter = {}  # base_filename -> counter for uniqueness

            def add_document(doc: Document, prefix: str = "") -> str:
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

            # Global preview image
            project_preview = None
            if getattr(project, 'preview_image', None) and project.preview_image.filename and project.preview_image.data:
                preview_path = add_document(project.preview_image, "previews/")
                if preview_path:
                    project_preview = {'filename': project.preview_image.filename, '_path': preview_path}

            # Global export history (XLSX files embedded in ZIP)
            export_history_for_json = []
            for entry in (getattr(project, 'export_history', None) or []):
                entry_copy = dict(entry)
                xlsx_b64 = entry_copy.pop('xlsx_data_b64', None)
                xlsx_path = entry_copy.get('_xlsx_path')
                if xlsx_b64 and xlsx_path:
                    doc_index[xlsx_path] = xlsx_b64
                export_history_for_json.append(entry_copy)

            # Serialize all versions
            versions_data = []
            for version in project.versions:
                v_prefix = f"v{version.version_index}/"

                # Version documents (plans)
                version_doc_paths = []
                for doc in version.documents:
                    path = add_document(doc, f"{v_prefix}project/")
                    if path:
                        version_doc_paths.append({'filename': doc.filename, '_path': path})

                # Operations and their cost documents
                ops_data = []
                for op in version.operations:
                    op_dict = dataclasses.asdict(op)
                    for cost_name, cost_data in op_dict.get('costs', {}).items():
                        cost_obj = op.costs.get(cost_name)
                        if cost_obj and cost_obj.documents:
                            cost_doc_paths = []
                            for doc in cost_obj.documents:
                                path = add_document(doc, f"{v_prefix}costs/{op.code}/")
                                if path:
                                    cost_doc_paths.append({'filename': doc.filename, '_path': path})
                            cost_data['documents'] = cost_doc_paths
                    ops_data.append(op_dict)

                version_dict = {
                    'version_index': version.version_index,
                    'label': version.label,
                    'created_at': version.created_at,
                    'created_from_version': version.created_from_version,
                    'operations': ops_data,
                    'documents': version_doc_paths,
                    'sale_quantities': version.sale_quantities,
                    'volume_margin_rates': {str(k): v for k, v in (version.volume_margin_rates or {}).items()},
                    'serie_data': dataclasses.asdict(version.serie_data) if version.serie_data else None,
                }
                versions_data.append(version_dict)

            project_dict = {
                'name': project.name,
                'reference': project.reference,
                'client': project.client,
                'mwq_uuid': project.mwq_uuid,
                'project_date': project.project_date,
                'is_prototype': project.is_prototype,
                'preview_image': project_preview,
                'export_history': export_history_for_json,
                'versions': versions_data,
                'current_version_index': project.current_version_index,
                '_mwq_version': MWQ_VERSION,
                '_content_hash': PersistenceService.compute_content_hash(project),
            }

            json_content = json.dumps(project_dict, cls=EnhancedJSONEncoder, indent=2, ensure_ascii=False)
            zf.writestr(PROJECT_JSON_FILENAME, json_content.encode('utf-8'))

            for doc_path, doc_data in doc_index.items():
                try:
                    binary_data = base64.b64decode(doc_data)
                    zf.writestr(doc_path, binary_data)
                except Exception as e:
                    print(f"Warning: Could not write document {doc_path}: {e}")

    @staticmethod
    def load_project(filepath: str) -> Project:
        if PersistenceService.is_zip_format(filepath):
            return PersistenceService._load_project_zip(filepath)
        else:
            return PersistenceService._load_project_legacy(filepath)

    @staticmethod
    def _load_project_zip(filepath: str) -> Project:
        with zipfile.ZipFile(filepath, 'r') as zf:
            json_content = zf.read(PROJECT_JSON_FILENAME).decode('utf-8')
            data = json.loads(json_content)

            # Load preview image (global)
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

            # Restore XLSX binaries in export_history
            raw_export_history = data.get('export_history', [])
            export_history = []
            for entry in raw_export_history:
                entry = dict(entry)
                xlsx_path = entry.get('_xlsx_path')
                if xlsx_path and xlsx_path in zf.namelist():
                    binary_data = zf.read(xlsx_path)
                    entry['xlsx_data_b64'] = base64.b64encode(binary_data).decode('ascii')
                export_history.append(entry)

            # --- v3.0: versioned format ---
            if 'versions' in data:
                versions = []
                for v_data in data['versions']:
                    v_prefix = f"v{v_data['version_index']}/"
                    version = PersistenceService._load_version(zf, v_data, v_prefix)
                    versions.append(version)

                return Project(
                    name=data['name'],
                    reference=data.get('reference', ""),
                    client=data.get('client', ""),
                    mwq_uuid=data.get('mwq_uuid', ""),
                    project_date=data.get('project_date'),
                    is_prototype=data.get('is_prototype', False),
                    preview_image=preview_image,
                    export_history=export_history,
                    versions=versions,
                    current_version_index=data.get('current_version_index', 1),
                )

            # --- v2.0: single-version legacy ZIP format ---
            # Migrate: wrap existing data as version 1
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
                    proj_docs.append(Document(filename=doc_ref['filename'], data=None))

            operations = PersistenceService._load_operations(zf, data.get('operations', []), "")

            return Project(
                name=data['name'],
                reference=data.get('reference', ""),
                client=data.get('client', ""),
                mwq_uuid=data.get('mwq_uuid', ""),
                project_date=data.get('project_date'),
                preview_image=preview_image,
                export_history=export_history,
                operations=operations,
                documents=proj_docs,
                sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
                volume_margin_rates=PersistenceService._migrate_volume_margins(data),
                serie_data=PersistenceService._load_serie_data(data.get('serie_data')),
            )

    @staticmethod
    def _load_version(zf: zipfile.ZipFile, v_data: dict, v_prefix: str) -> ProjectVersion:
        """Load a ProjectVersion from ZIP data."""
        # Version documents (plans)
        version_docs = []
        for doc_ref in v_data.get('documents', []):
            doc_path = doc_ref.get('_path')
            if doc_path and doc_path in zf.namelist():
                binary_data = zf.read(doc_path)
                version_docs.append(Document(
                    filename=doc_ref['filename'],
                    data=base64.b64encode(binary_data).decode('ascii')
                ))
            elif doc_ref.get('filename'):
                version_docs.append(Document(filename=doc_ref['filename'], data=None))

        operations = PersistenceService._load_operations(zf, v_data.get('operations', []), v_prefix)

        return ProjectVersion(
            version_index=v_data['version_index'],
            label=v_data.get('label', ""),
            created_at=v_data.get('created_at', ""),
            created_from_version=v_data.get('created_from_version'),
            operations=operations,
            documents=version_docs,
            sale_quantities=v_data.get('sale_quantities', [1, 10, 50, 100]),
            volume_margin_rates=PersistenceService._migrate_volume_margins(v_data),
            serie_data=PersistenceService._load_serie_data(v_data.get('serie_data')),
        )

    @staticmethod
    def _load_operations(zf: zipfile.ZipFile, ops_data: list, v_prefix: str) -> List[Operation]:
        """Load operations and their cost documents from ZIP."""
        operations = []
        for op_data in ops_data:
            costs = {}
            for cost_name, cost_data in op_data.get('costs', {}).items():
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
        return operations

    @staticmethod
    def _load_project_legacy(filepath: str) -> Project:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return PersistenceService.project_from_dict(data)

    @staticmethod
    def _build_cost_item(cost_data: Dict, docs: list) -> CostItem:
        ctype_val = cost_data.get('cost_type')
        if ctype_val == "Marge":
            return None

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
        """Reconstruct Project from dictionary (legacy JSON format)."""
        operations = []
        for op_data in data.get('operations', []):
            costs = {}
            for cost_name, cost_data in op_data.get('costs', {}).items():
                docs = []
                for d_data in cost_data.get('documents', []):
                    docs.append(Document(filename=d_data['filename'], data=d_data.get('data')))
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

        proj_docs = []
        for d_data in data.get('documents', []):
            proj_docs.append(Document(filename=d_data['filename'], data=d_data.get('data')))
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
            project_date=data.get('project_date'),
            preview_image=None,
            operations=operations,
            documents=proj_docs,
            sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
            volume_margin_rates=PersistenceService._migrate_volume_margins(data),
            serie_data=PersistenceService._load_serie_data(data.get('serie_data')),
        )

    @staticmethod
    def migrate_to_zip(filepath: str) -> bool:
        if PersistenceService.is_zip_format(filepath):
            return False
        try:
            project = PersistenceService._load_project_legacy(filepath)
            PersistenceService.save_project(project, filepath)
            return True
        except Exception as e:
            print(f"Migration error for {filepath}: {e}")
            return False

    @staticmethod
    def _migrate_volume_margins(data: dict) -> dict:
        rates = data.get('volume_margin_rates', {})
        if not rates and 'volume_margin_rate' in data:
            old_rate = data['volume_margin_rate']
            qtys = data.get('sale_quantities', [1, 10, 50, 100])
            rates = {str(q): old_rate for q in qtys}
        return {int(k): float(v) for k, v in rates.items()}

    @staticmethod
    def _load_serie_data(d) -> SerieData:
        if not d:
            return None

        fallback_tc = d.get('fallback_cycle_time_s', d.get('target_cycle_time_s', 0.0))

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
        project = PersistenceService.load_project(filepath)
        content_hash = PersistenceService.compute_content_hash(project)
        return project, content_hash
