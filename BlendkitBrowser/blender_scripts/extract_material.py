# blender -b file.blend --python extract_material.py -- --out DIR --name MATNAME
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import parse_args, emit  # noqa

import bpy  # noqa
import _matlib  # noqa


def pick_material(name):
    mats = [m for m in bpy.data.materials if m.node_tree and not getattr(m, "is_grease_pencil", False)]
    if not mats:
        return None
    for m in mats:
        if name and m.name == name:
            return m
    mats.sort(key=lambda m: len(m.node_tree.nodes), reverse=True)
    return mats[0]


def main():
    args = parse_args()
    out = args["out"]
    os.makedirs(out, exist_ok=True)
    mat = pick_material(args.get("name"))
    if not mat:
        return {"error": "no node material found in blend file"}
    man = _matlib.extract_manifest(mat, out)
    return {"procedural": man["procedural"], "warnings": man["warnings"], "channels": list(man["channels"])}


try:
    emit(main())
except Exception:
    emit({"error": traceback.format_exc()[-1500:]})
