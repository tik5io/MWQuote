# ui/dialogs/export_dialog.py
"""Dialog d'export sélectif vers le dossier projet réseau.

Remplace l'ancien « pavé » du panneau projet : un seul bouton « Exporter… »
ouvre ce dialog, qui présente

- la destination (dossier projet, proposé/parcourable) ;
- des cases rapides par catégorie (Plans, Offre client, Devis fournisseur,
  Fabrication/Qualité), cochées par défaut ;
- une arborescence fusionnant le dossier modèle réseau (0 - EMPTY PROJECT) et
  les éléments du projet, chaque élément rangé dans un sous-dossier par version
  (V1, V2…). Cases par dossier, avec option « inclure les sous-dossiers ».

Rien n'est copié tant que l'utilisateur n'a pas cliqué « Exporter » ; l'écrasement
d'un fichier déjà présent est demandé via une liste de sélection.
"""

import os

import wx
from wx.lib.agw import customtreectrl as CTC

from infrastructure.project_folder_service import (
    ProjectFolderService,
    ExportItem,
    CATEGORY_LABELS,
    CATEGORY_PLAN,
    CATEGORY_OFFER,
    CATEGORY_SUPPLIER,
    CATEGORY_FABRICATION,
)

# Catégories présentées comme cases rapides (dans l'ordre d'affichage).
_QUICK_CATEGORIES = [CATEGORY_PLAN, CATEGORY_OFFER, CATEGORY_SUPPLIER, CATEGORY_FABRICATION]

# Types de nœuds de l'arbre.
_KIND_FOLDER = "folder"        # dossier (modèle ou cible) à créer
_KIND_MODEL_FILE = "model"     # fichier du dossier modèle à copier
_KIND_ITEM = "item"            # élément du projet (ExportItem)


def _human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


class _Node:
    """Nœud intermédiaire de l'arbre (avant construction wx)."""

    __slots__ = ("name", "rel", "folders", "model_files", "items")

    def __init__(self, name, rel):
        self.name = name
        self.rel = rel                 # chemin relatif au dossier projet
        self.folders = {}              # name -> _Node
        self.model_files = []          # [(name, rel, size)]
        self.items = []                # [ExportItem]

    def folder(self, name):
        node = self.folders.get(name)
        if node is None:
            rel = os.path.join(self.rel, name) if self.rel else name
            node = _Node(name, rel)
            self.folders[name] = node
        return node


class ExportDialog(wx.Dialog):
    def __init__(self, parent, project, service=None):
        super().__init__(
            parent, title="Exporter vers le dossier projet",
            size=(720, 640),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.project = project
        self.service = service or ProjectFolderService()
        self._items = self.service.build_export_items(project)
        self._report = None            # rapport renvoyé après export

        self._build_ui()
        self._populate_tree()
        self._apply_quick_categories()

    # ------------------------------------------------------------------ #
    # Construction UI                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Destination ---
        dest_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Dossier projet (destination)")
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_ctrl = wx.TextCtrl(self)
        self.folder_ctrl.ChangeValue(getattr(self.project, "project_folder", "") or "")
        self.folder_ctrl.Bind(wx.EVT_TEXT, lambda e: self._update_status())
        row.Add(self.folder_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        suggest_btn = wx.Button(self, label="Proposer")
        suggest_btn.Bind(wx.EVT_BUTTON, self._on_suggest)
        row.Add(suggest_btn, 0, wx.RIGHT, 4)
        browse_btn = wx.Button(self, label="Parcourir…")
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)
        row.Add(browse_btn, 0)
        dest_box.Add(row, 0, wx.EXPAND | wx.ALL, 4)

        self.status_lbl = wx.StaticText(self, label="")
        dest_box.Add(self.status_lbl, 0, wx.LEFT | wx.BOTTOM, 6)
        sizer.Add(dest_box, 0, wx.EXPAND | wx.ALL, 8)

        # --- Cases rapides par catégorie ---
        quick_box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Éléments de l'offre à exporter")
        self._quick_checks = {}
        counts = self._category_counts()
        for cat in _QUICK_CATEGORIES:
            n = counts.get(cat, 0)
            chk = wx.CheckBox(self, label=f"{CATEGORY_LABELS[cat]} ({n})")
            chk.SetValue(True)
            chk.Enable(n > 0)
            chk.Bind(wx.EVT_CHECKBOX, lambda e, c=cat: self._on_quick_toggle(c))
            quick_box.Add(chk, 0, wx.ALL, 6)
            self._quick_checks[cat] = chk
        sizer.Add(quick_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # --- Option récursive ---
        self.recursive_chk = wx.CheckBox(self, label="Cocher/décocher un dossier affecte ses sous-dossiers")
        self.recursive_chk.SetValue(True)
        sizer.Add(self.recursive_chk, 0, wx.LEFT | wx.TOP, 12)

        # --- Arbre ---
        tree_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Arborescence à exporter")
        self.tree = CTC.CustomTreeCtrl(
            self, agwStyle=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT,
        )
        self.tree.Bind(CTC.EVT_TREE_ITEM_CHECKED, self._on_tree_checked)
        tree_box.Add(self.tree, 1, wx.EXPAND | wx.ALL, 4)

        toggle_row = wx.BoxSizer(wx.HORIZONTAL)
        all_btn = wx.Button(self, label="Tout cocher")
        none_btn = wx.Button(self, label="Tout décocher")
        all_btn.Bind(wx.EVT_BUTTON, lambda e: self._check_all(True))
        none_btn.Bind(wx.EVT_BUTTON, lambda e: self._check_all(False))
        toggle_row.Add(all_btn, 0, wx.RIGHT, 6)
        toggle_row.Add(none_btn, 0)
        tree_box.Add(toggle_row, 0, wx.ALL, 4)
        sizer.Add(tree_box, 1, wx.EXPAND | wx.ALL, 8)

        # --- Boutons ---
        btns = wx.StdDialogButtonSizer()
        self.export_btn = wx.Button(self, wx.ID_OK, "Exporter")
        self.export_btn.SetDefault()
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        btns.AddButton(self.export_btn)
        btns.AddButton(cancel_btn)
        btns.Realize()
        self.export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._update_status()

    # ------------------------------------------------------------------ #
    # Destination                                                         #
    # ------------------------------------------------------------------ #

    def _folder(self):
        return self.folder_ctrl.GetValue().strip()

    def _update_status(self):
        folder = self._folder()
        if not folder:
            self.status_lbl.SetLabel("Aucun dossier : il sera créé à l'export.")
            self.status_lbl.SetForegroundColour(wx.Colour(120, 120, 120))
        elif os.path.isdir(folder):
            self.status_lbl.SetLabel("✓ dossier existant")
            self.status_lbl.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.status_lbl.SetLabel("Le dossier sera créé à l'export.")
            self.status_lbl.SetForegroundColour(wx.Colour(150, 110, 0))
        self.export_btn.Enable(bool(folder))
        self.Layout()

    def _on_suggest(self, event):
        suggestion = self.service.suggest_folder(
            getattr(self.project, "client", "") or "",
            getattr(self.project, "reference", "") or "",
        )
        if not suggestion:
            wx.MessageBox(
                "Renseignez d'abord le client et/ou la référence du projet.",
                "Dossier projet", wx.OK | wx.ICON_INFORMATION, self,
            )
            return
        self.folder_ctrl.ChangeValue(suggestion)
        self._update_status()

    def _on_browse(self, event):
        current = self._folder()
        default = current if os.path.isdir(current) else self.service.get_root()
        with wx.DirDialog(
            self, "Choisir le dossier projet",
            defaultPath=default if os.path.isdir(default) else "",
            style=wx.DD_DEFAULT_STYLE,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.folder_ctrl.ChangeValue(dlg.GetPath())
                self._update_status()

    # ------------------------------------------------------------------ #
    # Arbre                                                               #
    # ------------------------------------------------------------------ #

    def _category_counts(self):
        counts = {}
        for it in self._items:
            counts[it.category] = counts.get(it.category, 0) + 1
        return counts

    def _build_node_tree(self):
        """Construit l'arbre intermédiaire (modèle + éléments projet)."""
        root = _Node("", "")

        # 1) Arbo du dossier modèle (dossiers + fichiers, y compris les lourds).
        template = self.service.get_template_folder()
        if os.path.isdir(template):
            for dirpath, _dirs, files in os.walk(template):
                rel = os.path.relpath(dirpath, template)
                node = root
                if rel != ".":
                    for part in rel.split(os.sep):
                        node = node.folder(part)
                for fname in files:
                    try:
                        size = os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        size = 0
                    frel = fname if rel == "." else os.path.join(rel, fname)
                    node.model_files.append((fname, frel, size))

        # 2) Éléments du projet, rangés sous leur sous-dossier cible (avec version).
        for item in self._items:
            node = root
            for part in item.rel_dir.split(os.sep):
                node = node.folder(part)
            node.items.append(item)

        return root

    def _populate_tree(self):
        self.tree.DeleteAllItems()
        self._node_data = {}   # tree item id -> dict(kind=..., ...)
        root_node = self._build_node_tree()
        hidden_root = self.tree.AddRoot("Projet")
        self._add_children(hidden_root, root_node)
        self.tree.ExpandAll()

    def _add_children(self, parent_item, node):
        for name in sorted(node.folders):
            child = node.folders[name]
            folder_item = self.tree.AppendItem(parent_item, name, ct_type=1)
            self.tree.SetItemBold(folder_item, True)
            self._node_data[folder_item] = {"kind": _KIND_FOLDER, "rel": child.rel}
            self._add_children(folder_item, child)

        for fname, frel, size in sorted(node.model_files):
            label = f"{fname}  ({_human_size(size)})" if size else fname
            leaf = self.tree.AppendItem(parent_item, label, ct_type=1)
            self._node_data[leaf] = {"kind": _KIND_MODEL_FILE, "rel": frel}

        for item in node.items:
            label = f"📄 {item.filename}  — {CATEGORY_LABELS.get(item.category, item.category)}"
            leaf = self.tree.AppendItem(parent_item, label, ct_type=1)
            self.tree.CheckItem2(leaf, True, torefresh=True)
            self._node_data[leaf] = {"kind": _KIND_ITEM, "item": item}

    def _on_tree_checked(self, event):
        item = event.GetItem()
        if self.recursive_chk.GetValue():
            self._cascade(item, self.tree.IsItemChecked(item))
        event.Skip()

    def _cascade(self, parent_item, state):
        child, cookie = self.tree.GetFirstChild(parent_item)
        while child:
            try:
                self.tree.CheckItem2(child, state, torefresh=True)
            except Exception:
                pass
            self._cascade(child, state)
            child, cookie = self.tree.GetNextChild(parent_item, cookie)

    def _iter_items(self):
        stack = [self.tree.GetRootItem()]
        while stack:
            it = stack.pop()
            if it in self._node_data:
                yield it, self._node_data[it]
            child, cookie = self.tree.GetFirstChild(it)
            while child:
                stack.append(child)
                child, cookie = self.tree.GetNextChild(it, cookie)

    def _check_all(self, state):
        for it, _data in self._iter_items():
            try:
                self.tree.CheckItem2(it, state, torefresh=True)
            except Exception:
                pass
        self.tree.Refresh()

    def _apply_quick_categories(self):
        """(Dé)coche les éléments du projet selon les cases rapides."""
        for it, data in self._iter_items():
            if data["kind"] != _KIND_ITEM:
                continue
            chk = self._quick_checks.get(data["item"].category)
            state = bool(chk and chk.IsChecked())
            try:
                self.tree.CheckItem2(it, state, torefresh=True)
            except Exception:
                pass
        self.tree.Refresh()

    def _on_quick_toggle(self, category):
        chk = self._quick_checks.get(category)
        state = bool(chk and chk.IsChecked())
        for it, data in self._iter_items():
            if data["kind"] == _KIND_ITEM and data["item"].category == category:
                try:
                    self.tree.CheckItem2(it, state, torefresh=True)
                except Exception:
                    pass
        self.tree.Refresh()

    # ------------------------------------------------------------------ #
    # Export                                                              #
    # ------------------------------------------------------------------ #

    def _collect_selection(self):
        create_dirs, model_files, items = [], [], []
        for it, data in self._iter_items():
            if not self.tree.IsItemChecked(it):
                continue
            kind = data["kind"]
            if kind == _KIND_FOLDER:
                create_dirs.append(data["rel"])
            elif kind == _KIND_MODEL_FILE:
                model_files.append(data["rel"])
            elif kind == _KIND_ITEM:
                items.append(data["item"])
        return create_dirs, model_files, items

    def _ask_overwrites(self, folder, create_dirs, model_files, items):
        """Pré-scan des fichiers déjà présents et sélection de ceux à écraser.

        Retourne (ok, set_rel_à_écraser) ; ok=False si l'utilisateur annule.
        """
        rels = list(model_files) + [it.rel_path for it in items]
        conflicts = sorted({rel for rel in rels if os.path.exists(os.path.join(folder, rel))})
        if not conflicts:
            return True, set()

        from ui.panels.project_panel import OverwriteSelectionDialog
        dlg = OverwriteSelectionDialog(self, folder, conflicts)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return False, set()
            return True, dlg.get_selected()
        finally:
            dlg.Destroy()

    def _on_export(self, event):
        folder = self._folder()
        if not folder:
            return

        create_dirs, model_files, items = self._collect_selection()
        if not (create_dirs or model_files or items):
            wx.MessageBox(
                "Rien n'est sélectionné à exporter.",
                "Export", wx.OK | wx.ICON_INFORMATION, self,
            )
            return

        ok, overwrites = (True, set())
        if os.path.isdir(folder):
            ok, overwrites = self._ask_overwrites(folder, create_dirs, model_files, items)
        if not ok:
            return

        decider = lambda rel: rel in overwrites

        progress = wx.ProgressDialog(
            "Export", "Copie en cours…",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE, parent=self,
        )
        try:
            report = self.service.run_export(
                self.project, folder, items,
                create_dirs=create_dirs, model_files=model_files,
                overwrite_decider=decider,
            )
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(f"Erreur lors de l'export :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR, self)
            return
        finally:
            try:
                progress.Destroy()
            except Exception:
                pass

        # Mémoriser le dossier sur le projet.
        self.project.project_folder = folder
        self._report = report
        self._show_report(folder, report)
        self.EndModal(wx.ID_OK)

    def _show_report(self, folder, report):
        errors = report.get("errors", [])
        summary = (
            f"Export terminé :\n{folder}\n\n"
            f"• Dossiers créés : {report.get('created_dirs', 0)}\n"
            f"• Fichiers copiés : {report.get('copied_files', 0)}\n"
            f"• Ignorés (non écrasés) : {report.get('skipped_files', 0)}\n"
            f"• Échecs : {len(errors)}"
        )
        if errors:
            summary += "\n\n⚠ Échecs :\n" + "\n".join(
                f"- {rel} : {msg}" for rel, msg in errors[:10]
            )
            if len(errors) > 10:
                summary += f"\n… (+{len(errors) - 10} autres)"
            wx.MessageBox(summary, "Export (avec erreurs)", wx.OK | wx.ICON_WARNING, self)
        else:
            wx.MessageBox(summary, "Export réussi", wx.OK | wx.ICON_INFORMATION, self)
