# -*- coding: utf-8 -*-
"""First-run license notice + small footer line shared by the Cinema 4D browser plugins.

The notice is shown once (until the user ticks the box and presses Continue). After that the
website the assets come from is opened in the default browser and the plugin window opens.
"""
import webbrowser

import c4d
from c4d import gui

ACK_KEY = "license_ack_v2"      # new key: the notice shows once again after updating

_ID_CHECK, _ID_OK, _ID_CANCEL = 5002, 5003, 5004
FOOTER_ID = 5100


# ---------------------------------------------------------------- "modal is open" flag
# Plugin windows pause their timers while the notice is open (several browser windows can be
# open at once, and their timers redrawing underneath made the notice flicker).
def is_showing():
    return bool(getattr(c4d, "_browser_license_showing", False))


def _set_showing(value):
    try:
        setattr(c4d, "_browser_license_showing", bool(value))
    except Exception:
        pass


# ---------------------------------------------------------------- footer (never forces a min width)
def footer_texts(site_name):
    return [
        "This plugin is only a browser. The license of every material, model, HDRI and scene "
        "is defined by %s - check it on the website before use." % site_name,
        "Browser only. Asset licenses are defined by %s - check them on the website." % site_name,
        "Licenses: see %s" % site_name,
    ]


class FooterArea(gui.GeUserArea):
    """One small grey line. It picks the longest text that fits and has a tiny minimum size,
    so it never stops the plugin window from being made smaller."""

    def __init__(self, texts):
        super().__init__()
        self.texts = texts

    def GetMinSize(self):
        return 40, 20

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.DrawSetPen(c4d.COLOR_BG)
        self.DrawRectangle(x1, y1, x2, y2)
        try:
            self.DrawSetFont(c4d.FONT_STANDARD)
        except Exception:
            pass
        room = max(10, self.GetWidth() - 14)
        text = None
        for t in self.texts:
            if self.DrawGetTextWidth(t) <= room:
                text = t
                break
        if text is None:
            text = self.texts[-1]
            while len(text) > 3 and self.DrawGetTextWidth(text + "..") > room:
                text = text[:-1]
            text += ".."
        self.DrawSetTextCol(c4d.COLOR_TEXT_DISABLED, c4d.COLOR_BG)
        self.DrawText(text, 7, max(0, (self.GetHeight() - self.DrawGetFontHeight()) // 2))


def add_footer(dlg, site_name):
    """Call at the end of CreateLayout()."""
    dlg._license_footer = FooterArea(footer_texts(site_name))
    dlg.AddUserArea(FOOTER_ID, c4d.BFH_SCALEFIT, 40, 20)
    dlg.AttachUserArea(dlg._license_footer, FOOTER_ID)


# ---------------------------------------------------------------- the notice
class LicenseDialog(gui.GeDialog):
    def __init__(self, plugin_name, site_name, kinds):
        super().__init__()
        self.plugin_name = plugin_name
        self.site_name = site_name
        self.kinds = kinds
        self.accepted = False

    def CreateLayout(self):
        self.SetTitle("%s - License notice" % self.plugin_name)
        # fixed-size layout (no scaling gadgets): nothing is re-laid-out while the dialog is open
        self.GroupBegin(0, c4d.BFH_LEFT | c4d.BFV_TOP, 1, 0, "", 0)
        self.GroupBorderSpace(16, 14, 16, 14)
        lines = [
            "%s is only a browser." % self.plugin_name,
            "",
            "It lets you search, download and import %s from %s." % (self.kinds, self.site_name),
            "It does not own, sell or change the license of any of that content.",
            "",
            "The license of every material, model, HDRI and scene follows the website",
            "it is downloaded from (%s) and the terms set by each asset's author." % self.site_name,
            "Please read the license of each asset on the website before you use it,",
            "especially in commercial projects.",
            "",
        ]
        for ln in lines:
            self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, ln, c4d.BORDER_NONE)
        self.AddCheckbox(_ID_CHECK, c4d.BFH_LEFT, 0, 0,
                         "I understand and agree: the license of the assets comes from %s" % self.site_name)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "", c4d.BORDER_NONE)
        self.GroupBegin(0, c4d.BFH_LEFT, 2, 0, "", 0)
        self.AddButton(_ID_OK, c4d.BFH_LEFT, 110, 0, "Continue")
        self.AddButton(_ID_CANCEL, c4d.BFH_LEFT, 110, 0, "Cancel")
        self.GroupEnd()
        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetBool(_ID_CHECK, False)
        self.Enable(_ID_OK, False)
        return True

    def Command(self, cid, msg):
        if cid == _ID_CHECK:
            self.Enable(_ID_OK, bool(self.GetBool(_ID_CHECK)))
        elif cid == _ID_OK:
            if self.GetBool(_ID_CHECK):
                self.accepted = True
                self.Close()
        elif cid == _ID_CANCEL:
            self.Close()
        return True


def ensure_ack(is_acked, set_acked, plugin_name, site_name, site_url, kinds):
    """True when the plugin may open.

    First run: shows the notice (modal). Closing it without ticking the box returns False and the
    plugin stays closed. On Continue the acknowledgement is stored, the website is opened in the
    browser and True is returned.
    """
    if is_acked():
        return True
    dlg = LicenseDialog(plugin_name, site_name, kinds)
    _set_showing(True)
    try:
        dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=0, defaulth=0)
    finally:
        _set_showing(False)
    if not dlg.accepted:
        return False
    set_acked()
    try:
        webbrowser.open(site_url)
    except Exception as e:  # noqa
        print("[%s] could not open %s: %s" % (plugin_name, site_url, e))
    return True
