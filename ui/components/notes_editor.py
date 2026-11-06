# ui/components/notes_editor.py
"""Bloc-notes riche du projet : gras, italique, souligné, puces, surlignage.

Le contenu est enregistré dans le projet sous forme de XML wx.richtext (`get_xml` / `set_xml`),
chaîne vide quand le bloc-notes est vide. Les modifications sont signalées avec un léger délai
(`on_changed(xml)`), pour ne pas sérialiser à chaque frappe ; `flush()` force l'envoi immédiat
(avant un enregistrement par exemple).

Raccourcis : Ctrl+G gras, Ctrl+I italique, Ctrl+U souligné (Ctrl+B est pris par le repli du
panneau Projet).
"""
import io

import wx
import wx.richtext as rtc

HIGHLIGHT = wx.Colour(255, 240, 140)
BULLET_INDENT = (100, 60)            # retrait de la puce et du texte, en dixièmes de mm


class NotesEditor(wx.Panel):
    SAVE_DELAY_MS = 500

    def __init__(self, parent, on_changed=None, min_height=150):
        super().__init__(parent)
        self.on_changed = on_changed
        self._loading = False
        self._dirty = False
        self._timer = wx.Timer(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_bold = self._tool("G", "Gras (Ctrl+G)", self._on_bold, wx.FONTWEIGHT_BOLD, wx.FONTSTYLE_NORMAL)
        self.btn_italic = self._tool("I", "Italique (Ctrl+I)", self._on_italic, wx.FONTWEIGHT_NORMAL, wx.FONTSTYLE_ITALIC)
        self.btn_underline = self._tool("S", "Souligné (Ctrl+U)", self._on_underline,
                                        wx.FONTWEIGHT_NORMAL, wx.FONTSTYLE_NORMAL, underline=True)
        self.btn_bullets = self._tool("•", "Liste à puces (paragraphe courant ou sélection)", self._on_bullets,
                                      wx.FONTWEIGHT_BOLD, wx.FONTSTYLE_NORMAL, width=30)
        self.btn_highlight = self._tool("Surligner", "Surligner la sélection (une seconde fois : retirer)",
                                        self._on_highlight, wx.FONTWEIGHT_NORMAL, wx.FONTSTYLE_NORMAL, width=66)
        self.btn_highlight.SetBackgroundColour(HIGHLIGHT)
        for i, btn in enumerate((self.btn_bold, self.btn_italic, self.btn_underline, self.btn_bullets, self.btn_highlight)):
            bar.Add(btn, 0, wx.RIGHT, 3 if i < 4 else 0)
        sizer.Add(bar, 0, wx.BOTTOM, 3)

        self.rt = rtc.RichTextCtrl(self, style=wx.BORDER_THEME | wx.VSCROLL | wx.WANTS_CHARS)
        self.rt.SetMinSize((-1, min_height))
        self.rt.SetBackgroundColour(wx.WHITE)
        sizer.Add(self.rt, 1, wx.EXPAND)
        self.SetSizer(sizer)

        for evt in (wx.EVT_TEXT, rtc.EVT_RICHTEXT_CONTENT_INSERTED, rtc.EVT_RICHTEXT_CONTENT_DELETED,
                    rtc.EVT_RICHTEXT_STYLE_CHANGED):
            self.rt.Bind(evt, self._on_modified)
        for evt in (rtc.EVT_RICHTEXT_SELECTION_CHANGED, wx.EVT_KEY_UP, wx.EVT_LEFT_UP):
            self.rt.Bind(evt, self._on_cursor_moved)
        self.rt.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_TIMER, lambda e: self.flush(), self._timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    # ------------------------------------------------------------------ barre d'outils

    def _tool(self, label, tooltip, handler, weight, style, underline=False, width=26):
        btn = wx.ToggleButton(self, label=label, size=(width, 24))
        font = btn.GetFont()
        font.SetWeight(weight)
        font.SetStyle(style)
        font.SetUnderlined(underline)
        btn.SetFont(font)
        btn.SetToolTip(tooltip)
        btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e: (handler(), self.rt.SetFocus(), self._refresh_tools()))
        return btn

    def _on_bold(self):
        self.rt.ApplyBoldToSelection()

    def _on_italic(self):
        self.rt.ApplyItalicToSelection()

    def _on_underline(self):
        self.rt.ApplyUnderlineToSelection()

    def _target_range(self):
        """Sélection, sinon paragraphe sous le curseur."""
        if self.rt.HasSelection():
            return self.rt.GetSelectionRange()
        para = self.rt.GetBuffer().GetParagraphAtPosition(self.rt.GetInsertionPoint())
        return para.GetRange() if para else rtc.RichTextRange(0, 0)

    def _paragraph_has_bullet(self, position):
        para = self.rt.GetBuffer().GetParagraphAtPosition(position)
        if not para:
            return False
        attr = para.GetAttributes()
        return attr.HasBulletStyle() and attr.GetBulletStyle() != wx.TEXT_ATTR_BULLET_STYLE_NONE

    def _on_bullets(self):
        rng = self._target_range()
        attr = rtc.RichTextAttr()
        attr.SetFlags(wx.TEXT_ATTR_BULLET_STYLE | wx.TEXT_ATTR_LEFT_INDENT)
        if self._paragraph_has_bullet(rng.GetStart()):
            attr.SetBulletStyle(wx.TEXT_ATTR_BULLET_STYLE_NONE)
            attr.SetLeftIndent(0, 0)
        else:
            attr.SetBulletStyle(wx.TEXT_ATTR_BULLET_STYLE_STANDARD)
            attr.SetLeftIndent(*BULLET_INDENT)
        self.rt.SetStyleEx(rng, attr, rtc.RICHTEXT_SETSTYLE_WITH_UNDO | rtc.RICHTEXT_SETSTYLE_PARAGRAPHS_ONLY)

    def _on_highlight(self):
        if not self.rt.HasSelection():
            return
        rng = self.rt.GetSelectionRange()
        current = rtc.RichTextAttr()
        self.rt.GetStyleForRange(rng, current)
        already = current.HasBackgroundColour() and current.GetBackgroundColour() == HIGHLIGHT
        attr = rtc.RichTextAttr()
        attr.SetFlags(wx.TEXT_ATTR_BACKGROUND_COLOUR)
        attr.SetBackgroundColour(wx.WHITE if already else HIGHLIGHT)
        self.rt.SetStyleEx(rng, attr, rtc.RICHTEXT_SETSTYLE_WITH_UNDO)

    def _refresh_tools(self):
        """État des boutons selon la sélection / le curseur."""
        try:
            self.btn_bold.SetValue(self.rt.IsSelectionBold())
            self.btn_italic.SetValue(self.rt.IsSelectionItalics())
            self.btn_underline.SetValue(self.rt.IsSelectionUnderlined())
            self.btn_bullets.SetValue(self._paragraph_has_bullet(self._target_range().GetStart()))
        except RuntimeError:
            pass

    def _on_cursor_moved(self, event):
        self._refresh_tools()
        event.Skip()

    def _on_key_down(self, event):
        if event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            handler = {ord("G"): self._on_bold, ord("I"): self._on_italic, ord("U"): self._on_underline}.get(event.GetKeyCode())
            if handler:
                handler()
                self._refresh_tools()
                return
        event.Skip()

    # ------------------------------------------------------------------ contenu

    def get_xml(self) -> str:
        """Contenu mis en forme (XML wx.richtext), « » si le bloc-notes est vide."""
        if not self.rt.GetValue().strip():
            return ""
        out = io.BytesIO()
        rtc.RichTextXMLHandler().SaveFile(self.rt.GetBuffer(), out)
        return out.getvalue().decode("utf-8")

    def set_xml(self, xml: str) -> None:
        """Charge un contenu enregistré (sans signaler de modification)."""
        self._loading = True
        try:
            self._timer.Stop()
            self._dirty = False
            self.rt.Clear()
            if xml:
                loaded = rtc.RichTextXMLHandler().LoadFile(self.rt.GetBuffer(), io.BytesIO(xml.encode("utf-8")))
                if not loaded:                      # contenu illisible : on l'affiche tel quel plutôt que de le perdre
                    self.rt.Clear()
                    self.rt.WriteText(xml)
            self.rt.SetInsertionPoint(0)
            self.rt.Refresh()
        finally:
            self._loading = False
        self._refresh_tools()

    def get_text(self) -> str:
        return self.rt.GetValue()

    # ------------------------------------------------------------------ signalement différé

    def _on_modified(self, event):
        event.Skip()
        if self._loading:
            return
        self._dirty = True
        self._timer.StartOnce(self.SAVE_DELAY_MS)

    def flush(self) -> None:
        """Envoie tout de suite les modifications en attente (sans effet si rien n'a changé)."""
        if self._dirty and not self._loading:
            self._dirty = False
            self._timer.Stop()
            if callable(self.on_changed):
                self.on_changed(self.get_xml())

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._timer.Stop()
        event.Skip()
