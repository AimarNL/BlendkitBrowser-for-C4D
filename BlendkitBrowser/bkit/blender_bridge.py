# -*- coding: utf-8 -*-
"""Locate Blender and run the conversion scripts in background mode."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from . import log as _log

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_scripts")


class BridgeError(Exception):
    pass


def _ver_key(path):
    m = re.search(r"Blender\s+(\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def find_blender(settings):
    p = (settings.get("blender_path") or "").strip()
    if p and os.path.isfile(p):
        return p
    env = os.environ.get("BLENDER_PATH")
    if env and os.path.isfile(env):
        return env
    cands = []
    if sys.platform.startswith("win"):
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cands += glob.glob(os.path.join(root, "Blender Foundation", "Blender *", "blender.exe"))
        cands += glob.glob(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
        cands.sort(key=_ver_key, reverse=True)
    elif sys.platform == "darwin":
        cands = ["/Applications/Blender.app/Contents/MacOS/Blender"]
    else:
        w = shutil.which("blender")
        cands = [w] if w else []
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def require_blender(settings):
    b = find_blender(settings)
    if not b:
        raise BridgeError("Blender was not found. Install Blender (free) or set its path in Settings.")
    return b


def run(blender, blend_path, script_name, args, timeout=1200):
    script = os.path.join(SCRIPTS_DIR, script_name)
    cmd = [blender, "--factory-startup", "-b", "-noaudio", blend_path, "--python", script, "--"] + list(args)
    _log.log("Blender: " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise BridgeError("Blender conversion timed out.")
    except OSError as e:
        raise BridgeError("Could not start Blender: %s" % e)
    out = proc.stdout.decode("utf-8", "replace")
    result = None
    for line in out.splitlines():
        if line.startswith("BKIT_RESULT:"):
            try:
                result = json.loads(line[len("BKIT_RESULT:"):])
            except ValueError:
                pass
    if result is None:
        _log.log("Blender output tail:\n" + out[-2500:])
        raise BridgeError("Blender conversion failed (exit %s). See blendkit.log." % proc.returncode)
    if result.get("error"):
        _log.log("Blender script error: %s" % result["error"])
        raise BridgeError("Conversion error: %s" % result["error"])
    return result
