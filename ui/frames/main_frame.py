# ui/main_frame.py
import wx
import os
import io
from domain.project import Project
from ui.panels.project_panel import ProjectPanel
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel
from ui.panels.sales_pricing_panel import SalesPricingPanel
from ui.panels.graph_analysis_panel import GraphAnalysisPanel
from ui.panels.serie_pricing_panel import SeriePricingPanel
from infrastructure.persistence import PersistenceService
from infrastructure.logging_service import clear_logs_directory
from infrastructure.export_service import ExportService
from infrastructure.database import Database
from infrastructure.indexer import Indexer
from infrastructure.configuration import ConfigurationService
from infrastructure.file_manager import FileManager
from core.app_icon import get_icon_path, load_icon_from_sheet, get_template_path
from infrastructure.template_manager import TemplateManager






class MainFrame(wx.Frame):
    """Fenêtre principale de l'application de chiffrage"""

    def __init__(self, project=None, clear_logs=False, filepath=None):
        super().__init__(None, title="MWQuote", size=(1200, 800))
        
        if clear_logs:
            clear_logs_directory()

        self.project = project or Project(name="", reference="", client="")
        self.current_path = filepath
        self._dirty = False
        
        # Services
        self.db = Database()
        self.indexer = Indexer(self.db)
        self.config = ConfigurationService.get_instance()
        self.template_manager = TemplateManager(self.db)
        self.export_service = ExportService(db=self.db)
        
        self._build_ui()
        self._create_menu_bar()
        self._connect_events()
        self._set_app_icon()
        
        if self.project:
            self._update_app_with_project(self.project)
        
        self.Show()

    def _set_app_icon(self):
        try:
            icon_path = get_icon_path()
            if icon_path.exists():
                self.SetIcon(wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

    def _create_menu_bar(self):
        """Crée la barre de menu"""
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        new_item = file_menu.Append(wx.ID_NEW, "&Nouveau\tCtrl+N")
        open_item = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O")
        save_item = file_menu.Append(wx.ID_SAVE, "&Enregistrer\tCtrl+S")
        save_as_item = file_menu.Append(wx.ID_SAVEAS, "Enregistrer &sous...\tCtrl+Shift+S")
        file_menu.AppendSeparator()
        duplicate_item = file_menu.Append(wx.ID_DUPLICATE, "&Dupliquer le projet")
        self._split_version_item = file_menu.Append(wx.ID_ANY, "Séparer la version courante en nouveau projet")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "&Quitter\tAlt+F4")

        menu_bar.Append(file_menu, "&Fichier")
        self.SetMenuBar(menu_bar)

        # Bindings
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, self._on_save_as, save_as_item)
        self.Bind(wx.EVT_MENU, self._on_duplicate, duplicate_item)
        self.Bind(wx.EVT_MENU, self._on_split_version, self._split_version_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        self.Bind(wx.EVT_CLOSE, self._on_close)



    def _build_ui(self):
        """Construit l'interface utilisateur"""
        splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)

        # Left column: Project information and preview
        left_panel = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        self.project_panel = ProjectPanel(left_panel)
        left_sizer.Add(self.project_panel, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        # Right column: version bar + editing notebook
        right_panel = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Version bar ---
        self.version_bar = wx.Panel(right_panel, style=wx.BORDER_SIMPLE)
        self.version_bar.SetBackgroundColour(wx.Colour(230, 235, 245))
        self._version_bar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._version_bar_sizer.Add(
            wx.StaticText(self.version_bar, label="  Versions :"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4
        )
        self._version_btns = []  # list of (version_index, ToggleButton)
        self._version_bar_sizer.AddStretchSpacer(1)

        # Bouton export XLSX — côté droit, permanent
        self._export_xlsx_btn = wx.Button(
            self.version_bar, label="💾  Créer Offre XLSX", size=(-1, 26)
        )
        self._export_xlsx_btn.SetToolTip(
            "Exporter la version courante vers un devis XLSX (offre de prix)"
        )
        self._export_xlsx_btn.Bind(wx.EVT_BUTTON, self._on_export_xlsx)
        self._version_bar_sizer.Add(
            self._export_xlsx_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8
        )

        self.version_bar.SetSizer(self._version_bar_sizer)
        right_sizer.Add(self.version_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # --- Notebook for editing tabs ---
        self.notebook = wx.Notebook(right_panel)

        self.editor_panel = OperationCostEditorPanel(self.notebook)
        self.editor_panel.set_database(self.db)
        self.notebook.AddPage(self.editor_panel, "Structure et Coûts")

        self.sales_panel = SalesPricingPanel(self.notebook)
        self.notebook.AddPage(self.sales_panel, "Tarif de Vente")

        self.analysis_panel = GraphAnalysisPanel(self.notebook)
        self.notebook.AddPage(self.analysis_panel, "Analyse Graphique")

        self.serie_panel = SeriePricingPanel(self.notebook)
        self.notebook.AddPage(self.serie_panel, "Production Série")

        right_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(left_panel, right_panel)
        splitter.SetSashPosition(400)
        splitter.SetMinimumPaneSize(250)

    def _connect_events(self):
        """Connecte les événements entre les panels"""
        self.editor_panel.on_operation_updated = self._on_operation_updated
        self.sales_panel.on_operation_updated = self._on_operation_updated
        self.project_panel.on_quantities_changed = self._on_quantities_changed
        self.serie_panel.on_serie_updated = self._on_serie_updated

        def on_proj_changed():
            self.editor_panel.update_root_label()
            self._mark_dirty()

        self.project_panel.on_project_changed = on_proj_changed

    def _update_app_with_project(self, project):
        """Met à jour tous les panels avec un nouveau projet"""
        self.project = project
        self._rebuild_version_bar()
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)
        self.analysis_panel.load_project(self.project)
        self.serie_panel.load_project(self.project)
        self._update_title()

    # ------------------------------------------------------------------ #
    # Version management                                                    #
    # ------------------------------------------------------------------ #

    def _rebuild_version_bar(self):
        """Reconstruit les boutons de version dans la barre."""
        # Remove existing version buttons (keep label and spacer)
        for _, btn in self._version_btns:
            self._version_bar_sizer.Detach(btn)
            btn.Destroy()
        self._version_btns.clear()

        if not self.project:
            self.version_bar.Layout()
            return

        current_idx = self.project.current_version_index
        sizer = self._version_bar_sizer

        # Insert version buttons after the label (index 1)
        insert_pos = 1
        for version in sorted(self.project.versions, key=lambda v: v.version_index):
            v_idx = version.version_index
            label = version.label.strip() if version.label.strip() else f"V{v_idx}"
            btn = wx.ToggleButton(self.version_bar, label=label, size=(-1, 26))
            btn.SetValue(v_idx == current_idx)
            btn.SetToolTip(
                f"Version {v_idx}" + (f" — {version.label}" if version.label.strip() else "") +
                f"\nCréée le {version.created_at[:10]}" +
                (f"\nDepuis V{version.created_from_version}" if version.created_from_version else "")
            )
            v_idx_captured = v_idx
            btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, idx=v_idx_captured: self._on_version_selected(idx))
            sizer.Insert(insert_pos, btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            self._version_btns.append((v_idx, btn))
            insert_pos += 1

        # "+" button to create a new version
        add_btn = wx.Button(self.version_bar, label="+  Nouvelle version", size=(-1, 26))
        add_btn.SetToolTip("Créer une nouvelle version à partir de la version courante")
        add_btn.Bind(wx.EVT_BUTTON, self._on_add_version)
        sizer.Insert(insert_pos, add_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self._version_btns.append((-1, add_btn))  # -1 = not a real version btn

        self.version_bar.Layout()
        self.version_bar.GetParent().Layout()

    def _on_version_selected(self, version_index: int):
        """Bascule vers une version du projet."""
        if not self.project or self.project.current_version_index == version_index:
            # Re-enforce toggle state (prevent deselecting active)
            for idx, btn in self._version_btns:
                if idx == version_index and hasattr(btn, 'SetValue'):
                    btn.SetValue(True)
            return

        # Proposer la sauvegarde si des modifications en attente
        if self._dirty:
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de changer de version ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
            )
            if res == wx.CANCEL:
                # Annuler : re-sélectionner la version courante dans la barre
                self._rebuild_version_bar()
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    self._rebuild_version_bar()
                    return

        self.project.switch_to_version(version_index)
        self._rebuild_version_bar()
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)
        self.analysis_panel.load_project(self.project)
        self.serie_panel.load_project(self.project)
        self._dirty = False
        self._update_title()

    def _on_add_version(self, event):
        """Crée une nouvelle version à partir de la version courante."""
        if not self.project:
            return

        # Proposer la sauvegarde si des modifications en attente
        if self._dirty:
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de créer une nouvelle version ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
            )
            if res == wx.CANCEL:
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    return

        dlg = wx.TextEntryDialog(
            self,
            "Libellé de la nouvelle version (optionnel) :",
            "Nouvelle version",
            ""
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        label = dlg.GetValue().strip()
        dlg.Destroy()

        new_version = self.project.add_version(label)
        self.project.switch_to_version(new_version.version_index)
        self._rebuild_version_bar()
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)
        self.analysis_panel.load_project(self.project)
        self.serie_panel.load_project(self.project)
        self._dirty = True  # La création d'une version est une modification
        self._update_title()

    def _on_split_version(self, event):
        """Sépare la version courante en un nouveau projet autonome."""
        if not self.project:
            return

        v_idx = self.project.current_version_index
        v_label = next(
            (v.label for v in self.project.versions if v.version_index == v_idx),
            ""
        )
        v_name = v_label.strip() if v_label.strip() else f"V{v_idx}"

        if wx.MessageBox(
            f"Créer un nouveau projet à partir de la version {v_name} ?\n\n"
            "Le nouveau projet héritera de la référence, du client, de la preview "
            "et des exports de cette version.",
            "Séparer la version",
            wx.YES_NO | wx.ICON_QUESTION
        ) != wx.YES:
            return

        try:
            new_project = self.project.split_version_to_project(v_idx)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la séparation : {e}", "Erreur", wx.OK | wx.ICON_ERROR)
            return

        root = self.config.get_quotes_root_folder()
        default_file = ""
        if root:
            try:
                default_file = FileManager.get_mwq_path(
                    root, new_project.mwq_uuid, new_project.reference, new_project.name
                )
            except Exception:
                pass

        with wx.FileDialog(
            self,
            f"Enregistrer le nouveau projet (version {v_name})",
            defaultFile=os.path.basename(default_file) if default_file else "",
            defaultDir=os.path.dirname(default_file) if default_file else "",
            wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            save_path = fd.GetPath()

        try:
            PersistenceService.save_project(new_project, save_path)
            self.indexer.index_file(save_path)
            wx.MessageBox(
                f"Version {v_name} séparée avec succès !\n{save_path}",
                "Séparation réussie",
                wx.OK | wx.ICON_INFORMATION
            )
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'enregistrement : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------ #
    # Export XLSX                                                          #
    # ------------------------------------------------------------------ #

    def _on_export_xlsx(self, event):
        """Exporte la version courante du projet en devis XLSX."""
        if not self.project:
            return

        # Vérifier le template
        template_path = str(get_template_path())
        if not os.path.exists(template_path):
            wx.MessageBox(
                f"Le template XLSX est introuvable :\n{template_path}\n\n"
                "Vérifiez que TEMPLATE.xlsx est présent dans le dossier 'assets'.",
                "Template manquant",
                wx.OK | wx.ICON_ERROR
            )
            return

        # Générer la référence devis
        reference = self.export_service.get_devis_reference(project=self.project)
        default_filename = self.export_service.get_default_filename(
            self.project, devis_ref=reference
        )

        # Demander le chemin de sortie
        with wx.FileDialog(
            self,
            "Enregistrer le devis XLSX",
            defaultDir=os.path.expanduser("~\\Desktop"),
            defaultFile=default_filename,
            wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            output_path = fd.GetPath()

        progress = wx.ProgressDialog(
            "Création de l'offre XLSX",
            "Génération du document à partir du template...",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        try:
            self.export_service.export_excel(
                self.project,
                template_path,
                output_path,
                devis_ref=reference
            )
            progress.Destroy()

            # Ouvrir le fichier automatiquement
            try:
                os.startfile(output_path)
            except Exception:
                pass

            wx.MessageBox(
                f"Offre XLSX créée avec succès !\n\n"
                f"Référence : {reference}\n"
                f"Version   : V{self.project.current_version_index}\n"
                f"Fichier   : {os.path.basename(output_path)}",
                "Succès",
                wx.OK | wx.ICON_INFORMATION
            )

        except PermissionError as e:
            progress.Destroy()
            wx.MessageBox(
                f"Impossible d'enregistrer le fichier.\n"
                "Vérifiez qu'il n'est pas déjà ouvert dans Excel.\n\n"
                f"Détail : {e}",
                "Erreur d'accès",
                wx.OK | wx.ICON_ERROR
            )
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(
                f"Erreur lors de la création de l'offre :\n{e}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _update_title(self):
        """Met à jour le titre de la fenêtre avec la référence ou le nom du projet."""
        if not self.project:
            self.SetTitle("MWQuote")
            return
        display_name = self.project.display_name
        v_idx = self.project.current_version_index
        dirty_marker = " ●" if self._dirty else ""
        self.SetTitle(f"MWQuote - {display_name}  [V{v_idx}]{dirty_marker}")

    def _on_operation_updated(self, operation, reload_header=False):
        """Appelé quand une opération est modifiée.

        Args:
            operation: L'opération modifiée (peut être None pour refresh sans contexte)
            reload_header: Si True, recharge aussi le project_panel (pour ajout/suppression d'opérations)
        """
        # Recharger le header seulement si explicitement demandé
        if reload_header:
            self.project_panel.load_project(self.project)

        # Rafraîchir tous les panels de données
        self._refresh_all_data_panels()
        self._mark_dirty()

    def _on_quantities_changed(self, quantities):
        """Appelé quand les quantités du projet sont modifiées."""
        self._refresh_all_data_panels()
        self.editor_panel.refresh_quantities()
        self.sales_panel.refresh_quantities()
        self._mark_dirty()

    def _on_serie_updated(self):
        """Appelé quand les données Série sont modifiées."""
        self._mark_dirty()

    def _refresh_all_data_panels(self):
        """Rafraîchit tous les panels de données (grid, graphiques, etc.)."""
        self.sales_panel.refresh_data()
        self.analysis_panel.refresh_data()
        self.serie_panel.refresh_data()

    def _on_new(self, event):
        """Réinitialise avec un nouveau projet"""
        if not self._confirm_discard_or_save():
            return
        new_project = Project(name="", reference="", client="", mwq_uuid=FileManager.generate_uuid())
        self._update_app_with_project(new_project)
        self.current_path = None
        self._dirty = False
        self._update_title()

    def _on_open(self, event):
        """Ouvre un projet depuis un fichier"""
        if not self._confirm_discard_or_save():
            return
        with wx.FileDialog(self, "Ouvrir un projet", wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            try:
                project = PersistenceService.load_project(path)
                self.current_path = path
                self._update_app_with_project(project)
                self._dirty = False
                self._update_title()
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_duplicate(self, event):
        """Duplique le projet actuel"""
        if not self.current_path:
            wx.MessageBox("Veuillez d'abord ouvrir un projet.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        base, ext = os.path.splitext(self.current_path)
        default_name = os.path.basename(base) + "_copie" + ext

        with wx.FileDialog(self, "Dupliquer le projet", 
                          defaultFile=default_name,
                          wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                # Use clone to reset milestones
                cloned_project = self.project.clone()
                PersistenceService.save_project(cloned_project, path)
                # Auto-index in DB
                self.indexer.index_file(path)
                wx.MessageBox(
                    "Projet dupliqué avec succès !",
                    "Information",
                    wx.OK | wx.ICON_INFORMATION
                )
            except Exception as e:
                wx.MessageBox(f"Erreur lors de la duplication : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_close(self, event):
        """Appelé à la fermeture de la fenêtre principale"""
        if self._dirty:
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de fermer ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_WARNING
            )
            if res == wx.CANCEL:
                event.Veto()
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    event.Veto()
                    return
        clear_logs_directory()
        self.Destroy()

    def _confirm_discard_or_save(self) -> bool:
        """Propose l'enregistrement si des modifications sont en attente.

        Returns True si on peut continuer (sauvegardé ou abandonné),
        False si l'utilisateur annule.
        """
        if not self._dirty:
            return True
        res = wx.MessageBox(
            "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous les enregistrer ?",
            "Modifications non enregistrées",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
        )
        if res == wx.CANCEL:
            return False
        if res == wx.YES:
            return self._save_project(allow_dialog=True)
        # NO → on abandonne les modifications
        return True

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _save_project(self, allow_dialog: bool = True) -> bool:
        """Enregistre le projet.

        Si aucun chemin connu, tente de déduire le chemin depuis le dossier racine.
        Si toujours absent et allow_dialog=True, ouvre un FileDialog.
        Retourne True si sauvegardé avec succès.
        """
        if not self.project:
            return False

        if not self.current_path:
            # Tenter de déduire le chemin depuis le dossier racine configuré
            root = self.config.get_quotes_root_folder()
            if root:
                mwq_uuid = self.project.mwq_uuid or FileManager.generate_uuid()
                self.project.mwq_uuid = mwq_uuid
                try:
                    self.current_path = FileManager.get_mwq_path(
                        root, mwq_uuid, self.project.reference, self.project.name
                    )
                except Exception:
                    self.current_path = None

            if not self.current_path:
                if not allow_dialog:
                    return False
                with wx.FileDialog(
                    self, "Enregistrer le projet",
                    wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
                ) as fd:
                    if fd.ShowModal() == wx.ID_CANCEL:
                        return False
                    self.current_path = fd.GetPath()

        try:
            PersistenceService.save_project(self.project, self.current_path)
            self.indexer.index_file(self.current_path)
            self.template_manager.record_project_template_usage(self.project)
            self._dirty = False
            self._update_title()
            return True
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'enregistrement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)
            return False

    def _on_save(self, event):
        self._save_project(allow_dialog=True)

    def _on_save_as(self, event):
        old_path = self.current_path
        self.current_path = None
        if not self._save_project(allow_dialog=True):
            self.current_path = old_path
