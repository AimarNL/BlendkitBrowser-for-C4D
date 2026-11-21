# -*- coding: utf-8 -*-
"""Blendkit Browser for Cinema 4D (Python plugin).

Browse, search and import Blendkit (ex-BlenderKit) HDRIs, materials and models.
Assets are downloaded with your own account/API key and converted via a
background Blender instance.
"""
import os
import sys

import c4d

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Unregistered development ID. Register your own at https://developers.maxon.net/ and change it here.
PLUGIN_ID = 1000011

from bkit import log as _log          # noqa: E402
from bkit.config import Settings      # noqa: E402
from bkit.api import Client           # noqa: E402
from bkit.tasks import TaskRunner     # noqa: E402
from bkit.ui import BrowserDialog     # noqa: E402
from bkit import licensenotice        # noqa: E402


class BlendkitCommand(c4d.plugins.CommandData):
    def __init__(self):
        self.settings = Settings()
        _log.init(self.settings.dir)
        self.client = Client(self.settings)
        self.runner = TaskRunner()
        self.dialog = None

    def _dlg(self):
        if self.dialog is None:
            self.dialog = BrowserDialog(self.settings, self.client, self.runner)
        return self.dialog

    def _acked(self):
        # first run: license notice (tick + Continue), then the website opens
        s = self.settings
        return licensenotice.ensure_ack(
            lambda: bool(s.get(licensenotice.ACK_KEY)),
            lambda: s.set(licensenotice.ACK_KEY, True),
            "Blendkit Browser", "blendkit.com", "https://www.blendkit.com",
            "HDRIs, materials, models and scenes")

    def Execute(self, doc):
        if not self._acked():
            return True
        return self._dlg().Open(dlgtype=c4d.DLG_TYPE_ASYNC, pluginid=PLUGIN_ID, defaultw=1250, defaulth=820)

    def RestoreLayout(self, sec_ref):
        if not self.settings.get(licensenotice.ACK_KEY):
            return True
        return self._dlg().Restore(pluginid=PLUGIN_ID, secret=sec_ref)


def main():
    icon = c4d.bitmaps.BaseBitmap()
    icon_path = os.path.join(HERE, "res", "icon.png")
    res = icon.InitWith(icon_path) if os.path.isfile(icon_path) else None
    if isinstance(res, tuple):
        res = res[0]
    if res != c4d.IMAGERESULT_OK:
        icon = None
    ok = c4d.plugins.RegisterCommandPlugin(PLUGIN_ID, "Blendkit Browser", 0, icon,
                                           "Browse and import Blendkit assets", BlendkitCommand())
    print("Blendkit Browser v2.9 %s" % ("registered" if ok else "FAILED to register"))


if __name__ == "__main__":
    main()
