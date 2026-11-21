# blender -b file.blend --python extract_hdri.py -- --out /path/name.exr
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import parse_args, emit  # noqa

import bpy  # noqa


def main():
    args = parse_args()
    out = args["out"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    imgs = [i for i in bpy.data.images if i.type == "IMAGE" and i.size[0] > 0]
    if not imgs:
        return {"error": "no image found in blend file"}
    imgs.sort(key=lambda i: (i.is_float, i.size[0] * i.size[1]), reverse=True)
    img = imgs[0]
    img.filepath_raw = out
    img.file_format = "OPEN_EXR"
    img.save()
    return {"path": out, "size": [img.size[0], img.size[1]]}


try:
    emit(main())
except Exception:
    emit({"error": traceback.format_exc()[-1500:]})
