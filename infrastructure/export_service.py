import os
import datetime
import calendar
from copy import copy
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from infrastructure.logging_service import get_module_logger

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

    def get_default_filename(self, project):
        """Génère le nom de fichier par défaut : DEVIS_REF-PART_REF-xQTYmin-xQTYmax.xlsx"""
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
    def export_excel(self, project, template_path, output_path, project_save_path=None):
        try:
            wb = load_workbook(template_path)
            ws = wb.active

            # 0. Generate devis reference
            ref_date = datetime.date.today()
            
            # IMPORTANT: Compter les exports précédents AVANT d'ajouter le nouveau
            # pour que la sous-version soit correcte
            if not hasattr(project, 'export_history'):
                project.export_history = []
            
            devis_ref = self.get_devis_reference(project)
            
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

            # 2. Préparer le commentaire global (toutes les opérations)
            all_comments = []
            
            # Add drawing reference header
            drawing_ref = project.drawing_filename if hasattr(project, 'drawing_filename') and project.drawing_filename else "N/A"
            all_comments.append(f"Référence du plan chiffré : {drawing_ref}")
            all_comments.append("")  # Empty line for separation
            
            for op in project.operations:
                if op.comment and op.comment.strip():
                    all_comments.append(op.comment.strip())
            global_comment = "\n".join(all_comments)

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
                
            if val == "PART_REF":
                cell.value = self._get_part_reference(project)
            elif val == "QTY_REF":
                cell.value = qty
            elif val == "PU_REF":
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

        # Determine reference date (used for both DATE_REF and VALIDITY_REF)
        # Always use today's date at the moment of export
        ref_date = datetime.date.today()

        if val == "DEVIS_REF":
            # Use the reference pre-calculated for this export session
            if hasattr(self, '_current_export_ref'):
                cell.value = self._current_export_ref
            else:
                cell.value = self.get_devis_reference(project)
        elif val == "PART_REF":
            cell.value = self._get_part_reference(project)
        elif val == "DATE_REF":
            cell.value = ref_date.strftime("%d/%m/%Y")
        elif val == "VALIDITY_REF":
            # Add exactly 1 month to ref_date
            month = ref_date.month - 1 + 1
            year = ref_date.year + month // 12
            month = month % 12 + 1
            day = min(ref_date.day, calendar.monthrange(year, month)[1])
            date_validity = datetime.date(year, month, day)
            cell.value = date_validity.strftime("%d/%m/%Y")
        elif val == "COMMENT_REF":
            cell.value = global_comment

    def _clear_row_placeholders(self, ws, row_idx):
        """Efface les placeholders d'une ligne avant de la masquer."""
        placeholders = ["PART_REF", "QTY_REF", "PU_REF", "DEVIS_REF", "DATE_REF", "VALIDITY_REF", "COMMENT_REF"]
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if cell.value in placeholders:
                cell.value = ""
