# ui/dialogs/settings_dialog.py
"""Réglages : point d'entrée unique des paramètres de l'application.

Dossiers (projets .mwq, PROJET SÉRIE réseau, sauvegardes) et sauvegarde. La fenêtre ne
modifie rien elle-même : `get_values()` rend les valeurs saisies et l'appelant les applique
(un changement de dossier des projets déclenche la migration des fichiers, par exemple).
"""
import datetime

import wx


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, config, backup_service_factory, on_backup_now=None, on_restore=None):
        """
        config                 ConfigurationService (valeurs courantes)
        backup_service_factory fonction(backup_dir) -> BackupService, pour afficher l'état des sauvegardes
        on_backup_now          fonction(backup_dir, on_done) : sauvegarde immédiate
        on_restore             fonction(backup_dir) : restauration depuis un zip
        """
        super().__init__(parent, title="Réglages", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._config = config
        self._factory = backup_service_factory
        self._on_backup_now = on_backup_now
        self._on_restore = on_restore

        root = wx.BoxSizer(wx.VERTICAL)

        # ---- Dossiers ----
        folders = wx.StaticBoxSizer(wx.VERTICAL, self, "Dossiers")
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=8)
        grid.AddGrowableCol(1, 1)

        self.projects_dir = self._picker(
            grid, "Projets (.mwq) :", config.get_quotes_root_folder() or "",
            "Dossier où sont enregistrés les fichiers projet. Le changer propose de migrer les fichiers existants.")
        self.series_dir = self._picker(
            grid, "Projets série (réseau) :", config.get_series_root_folder() or "",
            "Racine réseau des dossiers projet (ex. Z:\\0 - PROJET SERIE), utilisée par l'export du dossier projet.")
        grid.Add(wx.StaticText(self, label="Dossier modèle :"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.template_name = wx.TextCtrl(self, value=config.get_empty_project_name() or "")
        self.template_name.SetToolTip("Nom du dossier modèle copié pour créer un dossier projet (ex. 0 - EMPTY PROJECT).")
        grid.Add(self.template_name, 1, wx.EXPAND)
        folders.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(folders, 0, wx.EXPAND | wx.ALL, 10)

        # ---- Sauvegarde ----
        backup = wx.StaticBoxSizer(wx.VERTICAL, self, "Sauvegarde automatique (hebdomadaire)")
        bgrid = wx.FlexGridSizer(cols=2, hgap=10, vgap=8)
        bgrid.AddGrowableCol(1, 1)
        self.backup_dir = self._picker(
            bgrid, "Dossier des sauvegardes :", config.get_backup_folder(),
            "Idéalement sur un autre disque que les projets. Chaque sauvegarde est un zip "
            "(base + config + tous les .mwq) ; les 8 dernières sont conservées.", parent_box=backup)
        backup.Add(bgrid, 0, wx.EXPAND | wx.ALL, 8)
        self.backup_info = wx.StaticText(self, label="")
        backup.Add(self.backup_info, 0, wx.LEFT | wx.RIGHT, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_now = wx.Button(self, label="Sauvegarder maintenant")
        self.btn_now.Bind(wx.EVT_BUTTON, self._on_now)
        self.btn_restore = wx.Button(self, label="Restaurer une sauvegarde…")
        self.btn_restore.SetToolTip("Remplace la base et les projets par le contenu d'un zip de sauvegarde.")
        self.btn_restore.Bind(wx.EVT_BUTTON, self._on_restore_clicked)
        btns.Add(self.btn_now, 0, wx.RIGHT, 8)
        btns.Add(self.btn_restore, 0)
        backup.Add(btns, 0, wx.ALL, 10)
        root.Add(backup, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        root.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(root)
        self.SetMinSize((640, self.GetBestSize().height))
        self.SetSize((max(self.GetBestSize().width, 680), self.GetBestSize().height))
        self.backup_dir.Bind(wx.EVT_DIRPICKER_CHANGED, lambda e: self.refresh_backup_info())
        self.refresh_backup_info()

    def _picker(self, grid, label, path, tooltip, parent_box=None):
        grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        picker = wx.DirPickerCtrl(self, path=path or "", message=label.rstrip(" :"),
                                  style=wx.DIRP_USE_TEXTCTRL)
        picker.SetToolTip(tooltip)
        grid.Add(picker, 1, wx.EXPAND)
        return picker

    # ------------------------------------------------------------------ sauvegarde

    def refresh_backup_info(self):
        """« Dernière sauvegarde : … · N conservée(s) » pour le dossier saisi."""
        try:
            folder = self.backup_dir.GetPath()
            backups = self._factory(folder).list_backups() if folder else []
            if backups:
                last = backups[-1][0]
                text = f"Dernière sauvegarde : {last:%d/%m/%Y %H:%M}  ·  {len(backups)} conservée(s)"
            else:
                text = "Aucune sauvegarde dans ce dossier pour l'instant."
            self.backup_info.SetLabel(text)
            self.Layout()
        except RuntimeError:
            pass   # fenêtre fermée pendant une sauvegarde en cours

    def _on_now(self, event):
        if self._on_backup_now:
            self._on_backup_now(self.backup_dir.GetPath(), lambda: wx.CallAfter(self.refresh_backup_info))

    def _on_restore_clicked(self, event):
        if self._on_restore:
            self._on_restore(self.backup_dir.GetPath())

    # ------------------------------------------------------------------ valeurs

    def get_values(self) -> dict:
        return {
            "projects_dir": self.projects_dir.GetPath().strip(),
            "series_dir": self.series_dir.GetPath().strip(),
            "template_name": self.template_name.GetValue().strip(),
            "backup_dir": self.backup_dir.GetPath().strip(),
        }
