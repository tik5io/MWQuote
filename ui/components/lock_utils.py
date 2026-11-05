# ui/components/lock_utils.py
"""Verrouillage d'un contrôle quand le scénario est figé par une offre.

Un contrôle désactivé (`Enable(False)`) ne défile plus et ne se sélectionne plus. Les zones de
commentaire multi-lignes doivent rester lisibles en entier : on les passe donc en lecture
seule (`SetEditable(False)`), ce qui conserve la barre de défilement, la molette et la
sélection / copie du texte. Les autres contrôles sont désactivés comme avant.
"""
import wx


def is_scrollable_text(ctrl) -> bool:
    """Zone de texte multi-lignes (commentaires) : à garder défilable même verrouillée."""
    return isinstance(ctrl, wx.TextCtrl) and ctrl.IsMultiLine()


def lock_control(ctrl) -> bool:
    """Verrouille `ctrl`. Retourne True si quelque chose a changé (donc à restaurer plus tard).

    Une zone déjà en lecture seule ou un contrôle déjà désactivé n'est pas touché : au
    déverrouillage on ne doit pas leur donner une capacité qu'ils n'avaient pas.
    """
    if is_scrollable_text(ctrl):
        if ctrl.IsEditable():
            ctrl.SetEditable(False)
            return True
        return False
    if ctrl.IsEnabled():
        ctrl.Enable(False)
        return True
    return False


def unlock_control(ctrl) -> None:
    """Annule `lock_control` (les contrôles détruits depuis sont ignorés par l'appelant)."""
    if is_scrollable_text(ctrl):
        ctrl.SetEditable(True)
    else:
        ctrl.Enable(True)
