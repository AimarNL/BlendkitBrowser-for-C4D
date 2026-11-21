# -*- coding: utf-8 -*-
"""Persistent settings (JSON in the C4D prefs folder)."""
import json
import os

DEFAULTS = {
    "api_key": "",
    "api_base": "https://www.blendkit.com",
    "cache_dir": "",
    "blender_path": "",
    "model_format": "fbx",          # fbx | glb
    "material_target": "classic",   # classic | arnold
    "apply_to_selection": True,
    "renderer": "arnold",           # arnold | redshift | c4d
    "preview_size": 220,
    "last_type": "hdr",             # hdr | material | model
    "resolution_pref": "2K",
    "license_ack": False,           # first-run license notice accepted
}


def prefs_dir():
    base = None
    try:
        import c4d
        base = c4d.storage.GeGetStartupWritePath()
    except Exception:
        base = None
    if base:
        base = os.path.join(base, "prefs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".blendkit_c4d")
    d = os.path.join(base, "BlendkitBrowser")
    os.makedirs(d, exist_ok=True)
    return d


class Settings:
    def __init__(self, directory=None):
        self.dir = directory or prefs_dir()
        self.path = os.path.join(self.dir, "settings.json")
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.data.update(stored)
        except (OSError, ValueError):
            pass
        # 'Site / API URL' must be a real address; anything else (e.g. a pasted key) is reset
        base = str(self.data.get("api_base") or "").strip()
        host = base.split("//", 1)[-1].split("/", 1)[0].lower()
        if not (base.lower().startswith(("http://", "https://")) and
                ("blendkit" in host or "blenderkit" in host)):
            self.data["api_base"] = DEFAULTS["api_base"]

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            self.save()
