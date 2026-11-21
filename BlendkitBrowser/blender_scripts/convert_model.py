# blender -b file.blend --python convert_model.py -- --out DIR --name NAME --format fbx|glb
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import parse_args, emit  # noqa

import bpy  # noqa
import json  # noqa
import _matlib  # noqa


def main():
    args = parse_args()
    out = args["out"]
    name = args.get("name") or "model"
    fmt = (args.get("format") or "fbx").lower()
    os.makedirs(out, exist_ok=True)
    warnings = []

    scene = bpy.context.scene
    if len(scene.objects) == 0:
        for ob in bpy.data.objects:
            try:
                scene.collection.objects.link(ob)
            except Exception:
                pass
    is_scene = (args.get("scene") == "1")
    # models: drop cameras and lights; scenes keep them
    if not is_scene:
        for ob in list(bpy.data.objects):
            if ob.type in ("CAMERA", "LIGHT"):
                bpy.data.objects.remove(ob, do_unlink=True)
    if len(scene.objects) == 0:
        return {"error": "no objects found in blend file"}

    # ---- materials: extract with our own logic (FBX only carries very little of them)
    index = {"materials": {}, "objects": {}}
    mdir = os.path.join(out, "materials")
    for ob in scene.objects:
        if ob.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            continue
        names = []
        for slot in ob.material_slots:
            m = slot.material
            if not m:
                continue
            names.append(m.name)
            if m.name not in index["materials"]:
                d = os.path.join(mdir, _matlib.safe(m.name))
                try:
                    man = _matlib.extract_manifest(m, d)
                    index["materials"][m.name] = {"dir": d, "procedural": man["procedural"]}
                except Exception as e:
                    warnings.append("material %s: %s" % (m.name, e))
        if names:
            index["objects"][ob.name] = names
    with open(os.path.join(out, "materials.json"), "w") as f:
        json.dump(index, f, indent=2)

    try:
        bpy.ops.file.unpack_all(method="WRITE_LOCAL")
    except Exception as e:
        warnings.append("unpack: %s" % e)
    try:
        bpy.ops.object.select_all(action="SELECT")
    except Exception:
        pass

    if fmt == "glb":
        path = os.path.join(out, name + ".glb")
        try:
            bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True,
                                      export_cameras=is_scene)
        except TypeError:
            bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True)
    else:
        path = os.path.join(out, name + ".fbx")
        kw = dict(filepath=path, use_selection=False,
                  object_types=({"EMPTY", "ARMATURE", "MESH", "OTHER", "CAMERA", "LIGHT"} if is_scene
                                else {"EMPTY", "ARMATURE", "MESH", "OTHER"}),
                  use_mesh_modifiers=True, mesh_smooth_type="FACE", add_leaf_bones=False,
                  path_mode="COPY", embed_textures=False, bake_anim=False,
                  apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y")
        try:
            bpy.ops.export_scene.fbx(use_visible=True, **kw)
        except TypeError:
            bpy.ops.export_scene.fbx(**kw)
    if not os.path.isfile(path):
        return {"error": "export produced no file"}
    return {"path": path, "format": fmt, "objects": len(scene.objects), "warnings": warnings,
            "materials_index": os.path.join(out, "materials.json")}


try:
    emit(main())
except Exception:
    emit({"error": traceback.format_exc()[-1500:]})
