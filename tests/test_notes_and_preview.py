"""Bloc-notes riche du projet, aperçu sans cadre, noms de fichier longs."""
import base64
import io

import pytest
import wx

from domain.document import Document
from domain.project import Project
from infrastructure.persistence import PersistenceService


@pytest.fixture(scope="module")
def app():
    return wx.App(False)


@pytest.fixture
def frame(app):
    f = wx.Frame(None)
    yield f
    f.Destroy()


# --------------------------------------------------------------------------- modèle

def test_project_notes_default_and_split():
    p = Project(name="p", reference="R", client="C")
    assert p.notes == ""
    p.notes = "<xml/>"
    assert p.split_version_to_project(1).notes == "<xml/>"


def test_project_notes_survive_save_and_load(tmp_path):
    p = Project(name="p", reference="R", client="C", notes="<richtext>à garder é</richtext>")
    path = str(tmp_path / "p.mwq")
    PersistenceService.save_project(p, path)
    assert PersistenceService.load_project(path).notes == "<richtext>à garder é</richtext>"


def test_old_file_without_notes_loads_empty(tmp_path):
    import json, zipfile
    p = Project(name="p", reference="R", client="C")
    path = str(tmp_path / "p.mwq")
    PersistenceService.save_project(p, path)
    with zipfile.ZipFile(path) as zin:
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    with zipfile.ZipFile(path, "w") as zout:
        for i, data in items:
            if i.filename == "project.json":
                d = json.loads(data)
                d.pop("notes", None)
                data = json.dumps(d).encode("utf-8")
            zout.writestr(i, data)
    assert PersistenceService.load_project(path).notes == ""


# --------------------------------------------------------------------------- éditeur de notes

def _editor(frame, on_changed=None):
    from ui.components.notes_editor import NotesEditor
    return NotesEditor(frame, on_changed=on_changed)


def test_empty_editor_gives_empty_string(frame):
    assert _editor(frame).get_xml() == ""


def test_formatting_roundtrip(frame):
    a = _editor(frame)
    a.rt.WriteText("Titre ")
    a.rt.BeginBold(); a.rt.WriteText("gras"); a.rt.EndBold()
    a.rt.WriteText(" et ")
    a.rt.BeginItalic(); a.rt.WriteText("italique"); a.rt.EndItalic()
    xml = a.get_xml()
    assert xml.strip().startswith("<?xml") or "<richtext" in xml

    b = _editor(frame)
    b.set_xml(xml)
    assert b.get_text() == "Titre gras et italique"
    import wx.richtext as rtc
    attr = rtc.RichTextAttr()
    b.rt.GetStyleForRange(rtc.RichTextRange(6, 10), attr)
    assert attr.GetFontWeight() == wx.FONTWEIGHT_BOLD               # « gras » est resté en gras
    assert b.get_xml() == xml                                       # aller-retour stable


def test_bullets_toggle_and_survive_roundtrip(frame):
    a = _editor(frame)
    a.rt.WriteText("premier point")
    a._on_bullets()
    assert a._paragraph_has_bullet(0)
    xml = a.get_xml()
    assert "bullet" in xml.lower()
    b = _editor(frame)
    b.set_xml(xml)
    assert b._paragraph_has_bullet(0)
    b._on_bullets()                                                 # second clic : retire la puce
    assert not b._paragraph_has_bullet(0)


def test_highlight_toggles_on_selection(frame):
    from ui.components.notes_editor import HIGHLIGHT
    import wx.richtext as rtc
    a = _editor(frame)
    a.rt.WriteText("surligné")
    a.rt.SetSelection(0, 8)
    a._on_highlight()
    attr = rtc.RichTextAttr()
    a.rt.GetStyleForRange(rtc.RichTextRange(0, 8), attr)
    assert attr.HasBackgroundColour() and attr.GetBackgroundColour() == HIGHLIGHT
    a._on_highlight()
    a.rt.GetStyleForRange(rtc.RichTextRange(0, 8), attr)
    assert attr.GetBackgroundColour() != HIGHLIGHT


def test_changes_are_signalled_only_when_flushed_and_loading_is_silent(frame):
    received = []
    a = _editor(frame, on_changed=received.append)
    a.set_xml("")                                                   # un chargement ne signale rien
    a.flush()
    assert received == []
    a.rt.WriteText("note")
    assert received == []                                           # différé
    a.flush()
    assert len(received) == 1 and received[0] != ""
    a.flush()
    assert len(received) == 1                                       # rien de nouveau : pas de doublon


def test_unreadable_content_is_shown_not_lost(frame):
    a = _editor(frame)
    a.set_xml("texte brut sans XML")
    assert "texte brut sans XML" in a.get_text()


# --------------------------------------------------------------------------- panneau projet

def _png_b64(w, h, color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def panel(frame):
    from ui.panels.project_panel import ProjectPanel
    frame.SetSize((420, 800))
    p = ProjectPanel(frame)
    p.SetSize((400, 760))
    return p


def test_panel_has_no_preview_frame_and_two_small_buttons(panel):
    assert not hasattr(panel, "preview_pane")                       # plus de volet repliable ni de cadre
    assert panel.collect_preview_btn.GetLabel() == "Coller"
    assert panel.clear_preview_btn.GetLabel() == "Supprimer"
    # l'aperçu est en tête : au-dessus de la référence
    assert panel.preview_bitmap.GetPosition().y < panel.ref_ctrl.GetPosition().y


def test_preview_is_scaled_to_available_width_and_placeholder_when_empty(panel):
    panel.load_project(Project(name="p", reference="R", client="", preview_image=Document(
        filename="x.png", data=_png_b64(800, 200))))
    bmp = panel.preview_bitmap.GetBitmap()
    assert bmp.GetWidth() <= panel.PREVIEW_WIDTH and bmp.GetHeight() <= panel.PREVIEW_HEIGHT
    assert abs(bmp.GetWidth() / bmp.GetHeight() - 4.0) < 0.1        # le rapport de l'image est conservé
    assert panel._preview_source is not None

    panel.load_project(Project(name="p", reference="R", client=""))
    assert panel._preview_source is None                            # « Aucune image »


def test_notes_loaded_and_sent_back_to_project(panel):
    p = Project(name="p", reference="R", client="")
    panel.load_project(p)
    panel.notes.rt.WriteText("à retenir")
    panel.flush()
    assert p.notes != ""
    q = Project(name="q", reference="R", client="")
    panel.load_project(q)
    assert panel.notes.get_text() == ""                             # le bloc-notes suit le projet affiché
    panel.load_project(p)
    assert panel.notes.get_text() == "à retenir"


def test_long_file_names_are_ellipsized_with_full_name_in_tooltip(frame):
    from ui.components.document_list_panel import DocumentListPanel
    long_name = "e079003a-af93-4a61-b002-716cb72fbc39_Fuel injector - plan client révision C très long.pdf"
    dl = DocumentListPanel(frame, label="Plans :")
    dl.SetSize((300, 300))
    dl.load_documents([Document(filename=long_name, data="")])
    labels = [w for w in dl.list_panel.GetChildren() if isinstance(w, wx.StaticText)]
    assert labels and labels[0].GetWindowStyleFlag() & wx.ST_ELLIPSIZE_MIDDLE
    assert labels[0].GetToolTipText() == long_name
    assert labels[0].GetMinSize().width <= 10                       # peut rétrécir : ne force plus la largeur
