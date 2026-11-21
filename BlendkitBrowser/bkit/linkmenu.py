# -*- coding: utf-8 -*-
"""Right-click menu on an asset card: open the asset's page on the website / copy its link."""
import traceback
import webbrowser

import c4d
from c4d import gui

_OPEN = c4d.FIRST_POPUP_ID
_COPY = c4d.FIRST_POPUP_ID + 1


def _clean(text, n=30):
    text = (text or "").replace("&", "")
    return text if len(text) <= n else text[:n - 1] + "..."


def show(area, mx, my, site_name, url, name=""):
    try:
        _show(area, mx, my, site_name, url, name)
    except Exception:  # noqa
        print("[%s] right-click menu failed:" % site_name)
        traceback.print_exc()


def _show(area, mx, my, site_name, url, name=""):
    """Small popup right at the mouse. (mx, my) = mouse position inside the user area."""
    if not url:
        return
    bc = c4d.BaseContainer()
    label = ("Open \"%s\" on %s" % (_clean(name), site_name)) if name else ("Open page on %s" % site_name)
    bc.InsData(_OPEN, label)
    bc.InsData(_COPY, "Copy page link")
    org = area.Local2Screen()
    x, y = org["x"] + mx, org["y"] + my
    # ShowPopupDialog wants the owning dialog (GeDialog), not the user area
    dlg = getattr(area, "host", None)
    if not isinstance(dlg, gui.GeDialog):
        dlg = None
    try:
        res = gui.ShowPopupDialog(cd=dlg, bc=bc, x=x, y=y)
    except Exception:  # noqa
        print("[%s] right-click menu failed:" % site_name)
        traceback.print_exc()
        return
    if res == _OPEN:
        webbrowser.open(url)
    elif res == _COPY:
        c4d.CopyStringToClipboard(url)
