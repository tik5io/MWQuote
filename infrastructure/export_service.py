import os
import datetime
import calendar
from copy import copy
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from infrastructure.logging_service import get_module_logger
from domain.cost import CostType
from domain.quote_validator import QuoteValidator

logger = get_module_logger("ExportService", "export_project.log")


class ExportService:
    """
    Export Excel basé sur un template avec des placeholders pré-formatés.
    - Lignes 21 à 30 : lignes de quantité avec PART_REF (Col B), QTY_REF (Col I), PU_REF (Col K)
    - Autres placeholders globaux: DEVIS_REF, DATE_REF, VALIDITY_REF, COMMENT_REF
    
    Utilise QuoteNumberingService pour gérer les numéros de quote persistants.
    """

    def __init__(self, db=None):
        """Initialize avec optionnel DB pour numbering service."""
        self.db = db
        self.numbering_service = None
        if db:
            from infrastructure.quote_numbering_service import QuoteNumberingService
            self.numbering_service = QuoteNumberingService(db)

    def get_devis_reference(self, project=None, sub_version: int = None):
        """
        Génère la référence du devis avec numérotation persistante.
        Format: {prefix}{date}_{counter:03d}-{sub_version}
        Exemple: OD260202_001-1
        
        Logique:
        - Si la quote a déjà un numéro (dans export_history), le réutiliser
        - Sinon, assigner un nouveau numéro avec le compteur du jour
        - La sous-version s'incrémente à chaque export, peu importe le jour
        
        Args:
            project: Project object (for compatibility, can be None if using numbering_service)
            sub_version: Sub-version number. If None, uses history count for that project
        """
        
        # Si numbering service disponible, l'utiliser (meilleur système)
        if self.numbering_service and project and hasattr(project, 'export_history'):
            # Chercher si cette quote a déjà un numéro assigné dans son historique
            existing_ref = None
            for export_entry in project.export_history:
                devis_ref = export_entry.get('devis_ref') or export_entry.get('reference')
                if devis_ref and devis_ref.startswith('OD'):
                    # Extraire le numéro (sans la sous-version)
                    # Format: OD260202_001-1 → on veut OD260202_001
                    if '-' in devis_ref:
                        existing_ref = devis_ref.rsplit('-', 1)[0]
                    else:
                        existing_ref = devis_ref
                    break
            
            # Si un numéro existe, le réutiliser
            if existing_ref:
                quote_num = existing_ref
            else:
                # Sinon, obtenir un nouveau numéro (incrémente le compteur du jour)
                quote_num, counter = self.numbering_service.get_next_quote_number("OD")
            
            # Déterminer la sous-version (nombre d'exports précédents de cette quote + 1)
            if sub_version is None:
                sub_version = len(project.export_history) + 1
            
            return f"{quote_num}-{sub_version}"
        
        # Fallback ancien système (compatible)
        today = datetime.date.today()
        base_ref = f"OD{today.strftime('%y%m%d')}_001"
        
        if project and hasattr(project, 'export_history'):
            # Chercher si cette quote a déjà un numéro
            existing_ref = None
            for export_entry in project.export_history:
                devis_ref = export_entry.get('devis_ref') or export_entry.get('reference')
                if devis_ref and devis_ref.startswith('OD'):
                    if '-' in devis_ref:
                        existing_ref = devis_ref.rsplit('-', 1)[0]
                    else:
                        existing_ref = devis_ref
                    break
            
            if existing_ref:
                base_ref = existing_ref
            
            sub_version = len(project.export_history) + 1
            return f"{base_ref}-{sub_version}"
            
        return base_ref

    def get_default_filename(self, project, devis_ref: str = None):
        """Génère le nom de fichier par défaut : DEVIS_REF-PART_REF-xQTYmin-xQTYmax.xlsx"""
        if devis_ref is None:
            devis_ref = self.get_devis_reference(project)
        part_ref = self._get_part_reference(project)
        # Supprimer les espaces et caractères spéciaux du part_ref pour le nom de fichier
        clean_part_ref = "".join(c for c in part_ref if c.isalnum() or c in ('-', '_')).strip()
        
        quantities = sorted(project.sale_quantities)
        if not quantities:
            return f"{devis_ref}-{clean_part_ref}.xlsx"
        
        q_min = self._format_qty(quantities[0])
        q_max = self._format_qty(quantities[-1])
        
        if len(quantities) == 1:
            return f"{devis_ref}-{clean_part_ref}-x{q_min}.xlsx"
        else:
            return f"{devis_ref}-{clean_part_ref}-x{q_min}-x{q_max}.xlsx"

    def _format_qty(self, qty):
        """Formate la quantité avec x100, x1k, x10k etc. avec arrondis intelligents."""
        if qty <= 0: return "0"
        
        # Gestion des arrondis si proche de 100 ou 1000
        # (Si la différence est < 2%, on arrondit pour le nom de fichier)
        for base in [100, 1000, 10000]:
            if abs(qty - base) / base < 0.02:
                qty = base
                break

        if qty >= 1000000:
            val = qty / 1000000
            return f"{val:g}m"
        elif qty >= 1000:
            val = qty / 1000
            return f"{val:g}k"
        else:
            return str(int(qty))

    # =========================
    # PUBLIC
    # =========================
    def export_excel(self, project, template_path, output_path, project_save_path=None, devis_ref=None):
        try:
            wb = load_workbook(template_path)
            ws = wb.active

            # 0. Generate devis reference
            ref_date = datetime.date.today()
            
            # IMPORTANT: Compter les exports précédents AVANT d'ajouter le nouveau
            # pour que la sous-version soit correcte
            if not hasattr(project, 'export_history'):
                project.export_history = []
            
            if devis_ref is None:
                devis_ref = self.get_devis_reference(project)

            # Keep a fresh diagnostic snapshot during exports too.
            project.validation_report = QuoteValidator.validate(project)
            
            # THE CRITICAL STEP: Add to history NOW so placeholders use THE SAME reference
            project.export_history.append({
                "devis_ref": devis_ref,
                "date": ref_date.strftime("%d/%m/%Y"),
                "time": datetime.datetime.now().strftime("%H:%M")
            })

            # Placeholder replacement will now call get_devis_reference again, 
            # but daily_count will have increased, so we MUST use the devis_ref we just generated.
            self._current_export_ref = devis_ref

            # 1. Trier les quantités par ordre croissant
            quantities = sorted(project.sale_quantities)
            qty_count = len(quantities)
            qty_processed = 0

            # 2. Préparer le commentaire global dans l'ordre des opérations:
            # commentaires d'opérations + commentaires méthode des coûts outillage.
            global_comment = self._build_global_comment(project)
            tooling_lines = self._get_tooling_lines(project)

            logger.info(f"Export {qty_count} quantités vers le template.")

            # 3. Identifier les lignes de placeholders et les remplir
            rows_to_hide = []
            
            for row_idx in range(1, ws.max_row + 1):
                # La ligne 33 doit rester statique
                if row_idx == 33:
                    continue

                is_qty_row = False
                
                # Vérifier si c'est une ligne de quantité (PART_REF en colonne B)
                # STRICTEMENT limité aux lignes 21 à 30
                if 21 <= row_idx <= 30:
                    cell_b = ws.cell(row=row_idx, column=2)
                    if cell_b.value == "PART_REF":
                        if qty_processed < qty_count:
                            qty = quantities[qty_processed]
                            self._fill_qty_row(ws, row_idx, project, qty, global_comment)
                            qty_processed += 1
                            is_qty_row = True
                        else:
                            # Effacer les placeholders de la ligne avant de la masquer
                            self._clear_row_placeholders(ws, row_idx)
                            rows_to_hide.append(row_idx)
                            continue

                # 4. Remplacer les placeholders globaux sur toute la ligne
                if not is_qty_row:
                    self._replace_global_placeholders(ws, row_idx, project, global_comment)

            # 5. Masquer les lignes en trop (au lieu de les supprimer pour préserver les fusions)
            for row_idx in rows_to_hide:
                ws.row_dimensions[row_idx].hidden = True

            # 5.b Gestion des lignes outillage (TOOL_REF / QTY_REF / PTOOL_REF)
            self._fill_tooling_rows(ws, tooling_lines, project, global_comment)
            # 5.c Sécurise COMMENT_REF (certaines manipulations de lignes peuvent l'effacer)
            self._fill_comment_placeholders(ws, global_comment)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wb.save(output_path)

            logger.info(f"Export Excel réussi → {output_path}")

            # 6. Save project to persist history if path provided
            if project_save_path:
                from infrastructure.persistence import PersistenceService
                PersistenceService.save_project(project, project_save_path)
                logger.info(f"Projet mis à jour avec l'historique d'export → {project_save_path}")

        except PermissionError:
            msg = f"Impossible d'enregistrer le fichier '{os.path.basename(output_path)}'. Vérifiez qu'il n'est pas déjà ouvert dans Excel."
            logger.error(msg)
            raise Exception(msg)
        except Exception as e:
            logger.error("Erreur export Excel", exc_info=True)
            raise

    # =========================
    # PRIVATE
    # =========================
    def _get_part_reference(self, project):
        ref = getattr(project, "reference", "")
        if "Prototype" in getattr(project, "tags", []):
            ref = f"{ref} - PROTO"
        return ref

    def _fill_qty_row(self, ws, row_idx, project, qty, global_comment):
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            val = cell.value
            if not isinstance(val, str):
                continue
            token = val.strip()
                
            if token == "PART_REF":
                cell.value = self._get_part_reference(project)
            elif token == "QTY_REF":
                cell.value = qty
            elif token == "PU_REF":
                pu = project.total_price(qty)
                cell.value = pu
                cell.number_format = '€ #,##0.00'
            else:
                self._replace_cell_placeholder(cell, project, global_comment)

    def _replace_global_placeholders(self, ws, row_idx, project, global_comment):
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            self._replace_cell_placeholder(cell, project, global_comment)

    def _replace_cell_placeholder(self, cell, project, global_comment):
        val = cell.value
        if not isinstance(val, str):
            return
        token = val.strip()

        # Determine reference date (used for both DATE_REF and VALIDITY_REF)
        # Always use today's date at the moment of export
        ref_date = datetime.date.today()

        if token == "DEVIS_REF":
            # Use the reference pre-calculated for this export session
            if hasattr(self, '_current_export_ref'):
                cell.value = self._current_export_ref
            else:
                cell.value = self.get_devis_reference(project)
        elif token == "PART_REF":
            cell.value = self._get_part_reference(project)
        elif token == "CUSTOMER_NAME":
            cell.value = getattr(project, "client", "")
        elif token == "DATE_REF":
            cell.value = ref_date.strftime("%d/%m/%Y")
        elif token == "VALIDITY_REF":
            # Add exactly 1 month to ref_date
            month = ref_date.month - 1 + 1
            year = ref_date.year + month // 12
            month = month % 12 + 1
            day = min(ref_date.day, calendar.monthrange(year, month)[1])
            date_validity = datetime.date(year, month, day)
            cell.value = date_validity.strftime("%d/%m/%Y")
        elif token == "COMMENT_REF":
            cell.value = global_comment
        elif token == "IMAGE_PREVIEW":
            # injecter l'image preview dans le placeholder (zones déjà mergées dans le template)
            project_preview = getattr(project, 'preview_image', None)
            if project_preview and getattr(project_preview, 'data', None):
                try:
                    from openpyxl.drawing.image import Image as OpenpyxlImage
                    from PIL import Image as PilImage
                    import io
                    import base64

                    preview_data = base64.b64decode(project_preview.data)
                    preview_img = PilImage.open(io.BytesIO(preview_data))

                    # Taille de la vignette pour le placeholder (hauteur ligne 210px)
                    max_height = 210
                    max_width = 300
                    if hasattr(PilImage, 'Resampling'):
                        resample = PilImage.Resampling.LANCZOS
                    else:
                        resample = PilImage.ANTIALIAS
                    preview_img.thumbnail((max_width, max_height), resample)

                    image_stream = io.BytesIO()
                    preview_img.save(image_stream, format='PNG')
                    image_stream.seek(0)

                    img = OpenpyxlImage(image_stream)
                    ws = cell.parent
                    
                    # Placer l'image dans la cellule (les zones sont déjà mergées dans le template)
                    img.anchor = cell.coordinate
                    ws.add_image(img)
                    
                    # Ajuster la hauteur de la ligne pour accueillir l'image
                    ws.row_dimensions[cell.row].height = 210
                    
                    # Effacer le texte placeholder
                    cell.value = ""
                except Exception as e:
                    logger.error(f"Erreur lors de l'insertion d'image: {e}", exc_info=True)
                    cell.value = "Preview non disponible"
            else:
                cell.value = "Preview non fournie"

    def _clear_row_placeholders(self, ws, row_idx):
        """Efface les placeholders d'une ligne avant de la masquer."""
        placeholders = [
            "PART_REF", "QTY_REF", "PU_REF",
            "TOOL_REF", "PTOOL_REF",
            "DEVIS_REF", "DATE_REF", "VALIDITY_REF", "CUSTOMER_NAME"
        ]
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if isinstance(cell.value, str) and cell.value.strip() in placeholders:
                cell.value = ""

    def _get_tooling_lines(self, project):
        lines = []
        for op in getattr(project, "operations", []):
            for cost in getattr(op, "costs", {}).values():
                if getattr(cost, "cost_type", None) == CostType.TOOLING:
                    lines.append(cost)
        return lines

    def _find_rows_with_placeholder(self, ws, placeholder):
        rows = []
        for row_idx in range(1, ws.max_row + 1):
            for col_idx in range(1, ws.max_column + 1):
                val = ws.cell(row=row_idx, column=col_idx).value
                if isinstance(val, str) and val.strip() == placeholder:
                    rows.append(row_idx)
                    break
        return rows

    def _clone_row_format(self, ws, source_row, target_row):
        for col_idx in range(1, ws.max_column + 1):
            src = ws.cell(row=source_row, column=col_idx)
            dst = ws.cell(row=target_row, column=col_idx)
            dst.value = src.value
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
            dst.number_format = src.number_format
            dst.protection = copy(src.protection)
        src_dim = ws.row_dimensions[source_row]
        ws.row_dimensions[target_row].height = src_dim.height
        ws.row_dimensions[target_row].hidden = src_dim.hidden

    def _fill_tool_row(self, ws, row_idx, tool_cost, project, global_comment):
        price = 0.0
        if getattr(tool_cost, "pricing", None):
            # Outillage exporté en ligne unitaire x1: on utilise le montant de lot.
            price = float(getattr(tool_cost.pricing, "fixed_price", 0.0) or 0.0)

        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            val = cell.value
            if not isinstance(val, str):
                continue
            token = val.strip()
            if token == "TOOL_REF":
                cell.value = "OUTILLAGE"
            elif token == "QTY_REF":
                cell.value = 1
            elif token == "PTOOL_REF":
                cell.value = price
                cell.number_format = '€ #,##0.00'
            else:
                self._replace_cell_placeholder(cell, project, global_comment)
        ws.row_dimensions[row_idx].hidden = False

    def _fill_tooling_rows(self, ws, tooling_lines, project, global_comment):
        tool_rows = self._find_rows_with_placeholder(ws, "TOOL_REF")
        if not tool_rows:
            return

        template_row = tool_rows[0]
        if not tooling_lines:
            for row_idx in tool_rows:
                self._clear_row_placeholders(ws, row_idx)
                ws.row_dimensions[row_idx].hidden = True
            return

        extra_needed = max(0, len(tooling_lines) - 1)
        if extra_needed > 0:
            ws.insert_rows(template_row + 1, amount=extra_needed)
            for i in range(extra_needed):
                self._clone_row_format(ws, template_row, template_row + 1 + i)

        for idx, tool_cost in enumerate(tooling_lines):
            self._fill_tool_row(ws, template_row + idx, tool_cost, project, global_comment)

    def _fill_comment_placeholders(self, ws, global_comment):
        replaced = 0
        for row_idx in range(1, ws.max_row + 1):
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if isinstance(cell.value, str) and cell.value.strip() == "COMMENT_REF":
                    cell.value = global_comment
                    replaced += 1
        logger.info(f"COMMENT_REF replaced count: {replaced}")

    def _build_global_comment(self, project):
        lines = []
        for op in getattr(project, "operations", []):
            if getattr(op, "comment", None) and op.comment.strip():
                lines.append(op.comment.strip())
            for cost in getattr(op, "costs", {}).values():
                if getattr(cost, "cost_type", None) == CostType.TOOLING:
                    if getattr(cost, "client_comment", None) and cost.client_comment.strip():
                        lines.append(cost.client_comment.strip())
        text = "\n".join(lines) if lines else "-"
        logger.info(f"Global comment lines: {len(lines)}")
        return text

    def export_fabrication_quality(self, project, output_path):
        """
        Export Fabrication/Qualité - Document Excel avec la trame de fabrication hiérarchique
        et les informations de temps et commentaires pour chaque opération.
        """
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

            wb = Workbook()
            ws = wb.active
            ws.title = "Fabrication_Qualité"

            # Styles
            header_font = Font(bold=True, size=12)
            subheader_font = Font(bold=True, size=10)
            normal_font = Font(size=10)
            border = Border(left=Side(style='thin'), right=Side(style='thin'),
                          top=Side(style='thin'), bottom=Side(style='thin'))
            header_fill = PatternFill(start_color="FFE6E6FA", end_color="FFE6E6FA", fill_type="solid")

            # En-têtes
            headers = ["Opération", "Typologie", "Temps fixe (h)", "Temps/pièce (h)",
                      "Commentaire Chiffrage", "Commentaire Méthode", "Preview"]
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = border
                cell.fill = header_fill

            # Ajuster la largeur des colonnes
            ws.column_dimensions['A'].width = 30  # Opération
            ws.column_dimensions['B'].width = 20  # Typologie
            ws.column_dimensions['C'].width = 15  # Temps fixe
            ws.column_dimensions['D'].width = 15  # Temps/pièce
            ws.column_dimensions['E'].width = 40  # Commentaire Chiffrage
            ws.column_dimensions['F'].width = 40  # Commentaire Méthode
            ws.column_dimensions['G'].width = 20  # Preview (vignette image ou libellé)

            row = 2

            # Informations du projet en en-tête
            ws.cell(row=row, column=1, value=f"Nom du projet : {getattr(project, 'name', 'N/A')}")
            ws.cell(row=row, column=2, value=f"Référence projet : {getattr(project, 'reference', 'N/A')}")
            row += 1

            # Référence du plan / documents
            drawing_name = getattr(project, 'drawing_filename', None) or 'N/A'
            ws.cell(row=row, column=1, value=f"Référence plan : {drawing_name}")
            ws.cell(row=row, column=2, value=f"Client : {getattr(project, 'client', 'N/A')}")
            row += 1

            # Preview image (si disponible)
            from openpyxl.drawing.image import Image as OpenpyxlImage
            from PIL import Image as PilImage
            import io
            import base64

            if getattr(project, 'preview_image', None) is not None and getattr(project.preview_image, 'data', None):
                try:
                    preview_data = base64.b64decode(project.preview_image.data)
                    preview_img = PilImage.open(io.BytesIO(preview_data))
                    # redimensionner pour éviter une insertion trop grande
                    max_width, max_height = 350, 250
                    preview_img.thumbnail((max_width, max_height), PilImage.Resampling.LANCZOS if hasattr(PilImage, 'Resampling') else PilImage.ANTIALIAS)
                    img_io = io.BytesIO()
                    preview_img.save(img_io, format='PNG')
                    img_io.seek(0)

                    img = OpenpyxlImage(img_io)
                    img.anchor = f"G{row}"
                    ws.add_image(img)
                    ws.row_dimensions[row].height = 180
                except Exception:
                    # Si l'image ne peut être insérée, on laisse juste le texte
                    ws.cell(row=row, column=1, value='Preview disponible mais impossible à afficher')

                row += 5

            # Parcourir les opérations
            for op in getattr(project, "operations", []):
                # Ligne d'opération
                ws.cell(row=row, column=1, value=f"🔧 {op.label}").font = subheader_font
                ws.cell(row=row, column=2, value=op.typology or "").font = normal_font
                ws.cell(row=row, column=5, value=op.comment or "").font = normal_font
                ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True)

                # Calculer les temps totaux pour l'opération
                total_fixed_time = 0.0
                total_per_piece_time = 0.0
                method_comments = []

                for cost_name, cost in op.costs.items():
                    if cost.cost_type == CostType.INTERNAL_OPERATION:
                        total_fixed_time += cost.fixed_time
                        total_per_piece_time += cost.per_piece_time

                    # Collecter les commentaires méthode
                    if hasattr(cost, 'comment') and cost.comment and cost.comment.strip():
                        method_comments.append(f"{cost.name}: {cost.comment.strip()}")

                ws.cell(row=row, column=3, value=round(total_fixed_time, 3) if total_fixed_time > 0 else "").font = normal_font
                ws.cell(row=row, column=4, value=round(total_per_piece_time, 3) if total_per_piece_time > 0 else "").font = normal_font
                ws.cell(row=row, column=6, value="\n".join(method_comments)).font = normal_font
                ws.cell(row=row, column=6).alignment = Alignment(wrap_text=True)

                # Appliquer les bordures
                for col in range(1, 7):
                    cell = ws.cell(row=row, column=col)
                    cell.border = border

                row += 1

                # Ligne de séparation si nécessaire
                if row > 2:
                    for col in range(1, 7):
                        ws.cell(row=row, column=col).border = Border(bottom=Side(style='thin'))

            # Ajuster la hauteur des lignes pour le texte wrappé
            for r in range(1, row):
                ws.row_dimensions[r].height = None  # Auto-height

            # Sauvegarder
            wb.save(output_path)

            logger.info(f"Export Fabrication/Qualité réussi → {output_path}")
            return True

        except Exception as e:
            logger.error("Erreur export Fabrication/Qualité", exc_info=True)
            raise
