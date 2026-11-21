# -*- coding: utf-8 -*-
"""Build materials in Cinema 4D from an extracted manifest: Arnold / Redshift node materials or Standard."""
import os

import c4d

from . import log as _log

ARNOLD = {
    "name": "Arnold",
    "space": "com.autodesk.arnold.nodespace",
    "surface_hint": "standard_surface",
    "image_ids": ["com.autodesk.arnold.shader.image", "com.autodesk.arnold.image", "com.autodesk.arnold.node.image"],
    "path_port": ["filename"], "path_child": None, "cs_port": ["color_space"],
    "image_out": ["output", "out", "rgba"],
    "normal_ids": ["com.autodesk.arnold.shader.normal_map", "com.autodesk.arnold.normal_map"],
    "normal_in": ["input"], "normal_out": ["output", "out"], "normal_type": None,
    "bump_ids": ["com.autodesk.arnold.shader.bump2d", "com.autodesk.arnold.bump2d"],
    "bump_in": ["bump_map"], "bump_type": None,
    "ports": {"color": ["base_color"], "roughness": ["specular_roughness"], "metallic": ["metalness"],
              "alpha": ["opacity"], "emission": ["emission_color"], "transmission": ["transmission"],
              "ior": ["specular_ior", "specular_IOR"], "normal": ["normal"], "emission_weight": ["emission"]},
}
REDSHIFT = {
    "name": "Redshift",
    "space": "com.redshift3d.redshift4c4d.class.nodespace",
    "surface_hint": "standardmaterial",
    "image_ids": ["com.redshift3d.redshift4c4d.nodes.core.texturesampler"],
    "path_port": ["tex0"], "path_child": "path", "cs_port": [],
    "image_out": ["outcolor", "out"],
    "normal_ids": ["com.redshift3d.redshift4c4d.nodes.core.bumpmap"],
    "normal_in": ["input"], "normal_out": ["out", "outdisplacementvector"], "normal_type": 1,
    "bump_ids": ["com.redshift3d.redshift4c4d.nodes.core.bumpmap"],
    "bump_in": ["input"], "bump_type": 0,
    "ports": {"color": ["base_color"], "roughness": ["refl_roughness"], "metallic": ["metalness"],
              "alpha": ["opacity_color"], "emission": ["emission_color"], "transmission": ["refr_weight"],
              "ior": ["refr_ior"], "normal": ["bump_input"], "emission_weight": ["emission_weight"]},
}
ARNOLD.update({
    "token": "arnold",
    "spaces": ["com.autodesk.arnold.nodespace", "com.autodesk.arnold.class.nodespace",
               "com.autodesk.arnold.nodes.nodespace", "com.solidangle.arnold.nodespace",
               "com.arnold.nodespace"],
    "openpbr_ids": ["com.autodesk.arnold.shader.open_pbr_surface", "com.autodesk.arnold.open_pbr_surface"],
    "openpbr_suffixes": ("open_pbr_surface", "openpbr"),
    "openpbr_ports": {"color": ["base_color"], "roughness": ["specular_roughness"], "metallic": ["base_metalness"],
                      "alpha": ["geometry_opacity"], "emission": ["emission_color"],
                      "transmission": ["transmission_weight"], "ior": ["specular_ior"],
                      "normal": ["geometry_normal"], "emission_weight": ["emission_luminance"]},
    "suffix": {"image": ("shader.image", ".image"), "normal": ("normal_map",), "bump": ("bump2d",)},
})
REDSHIFT.update({
    "token": "redshift",
    "openpbr_ids": ["com.redshift3d.redshift4c4d.nodes.core.openpbrmaterial",
                    "com.redshift3d.redshift4c4d.nodes.core.openpbr"],
    "openpbr_suffixes": ("openpbrmaterial", "openpbr", "openpbr_material"),
    "openpbr_ports": {"color": ["base_color"], "roughness": ["specular_roughness"], "metallic": ["base_metalness"],
                      "alpha": ["geometry_opacity"], "emission": ["emission_color"],
                      "transmission": ["transmission_weight"], "ior": ["specular_ior"],
                      "normal": ["geometry_normal"], "emission_weight": ["emission_luminance"]},
    "suffix": {"image": ("texturesampler",), "normal": ("bumpmap", "normalmap"), "bump": ("bumpmap",)},
})
SPECS = {"redshift": REDSHIFT}   # Arnold goes through Arnold's own converter (arnold_convert)
_dumped = set()
CONVERT_ENGINES = ("arnold", "octane", "corona", "vray")   # built as a C4D material, then converted by the renderer's own command
SET_COLORSPACE = False      # colour space handling is switched off for now (left at the shader default)


# --------------------------------------------------------------- node materials
def _build_node_material(name, manifest, base, spec, dump_path, mode):
    import maxon
    from . import nodegraph as ng

    channels = manifest.get("channels", {})
    values = manifest.get("values", {})
    warns = []
    spaces = spec.get("spaces") or [spec["space"]]
    mat = graph = None
    nodes = []
    for sp in spaces:
        try:
            space = maxon.Id(sp)
            m = c4d.BaseMaterial(c4d.Mmaterial)
            m.SetName(name)
            nm = m.GetNodeMaterialReference()
            nm.CreateDefaultGraph(space)
            g = nm.GetGraph(space)
            ns = ng.collect(g)
            if ns:
                mat, graph, nodes = m, g, ns
                _log.log("node space in use: %s (%d default nodes)" % (sp, len(ns)))
                break
            _log.log("node space %s gave an empty graph" % sp)
        except Exception as e:  # noqa
            _log.log("node space %s failed: %r" % (sp, e))
    if graph is None:
        raise RuntimeError("no %s node space worked (tried %s)" % (spec["name"], spaces))
    if spec["name"] not in _dumped:
        _dumped.add(spec["name"])
        ng.dump_graph(graph, dump_path, spec["name"] + " default graph")
    surf = next((n for n in nodes if spec["surface_hint"] in ng.asset_id(n).lower()), None)
    if surf is None:
        raise RuntimeError("%s surface node not found (nodes: %s)" % (spec["name"], [ng.asset_id(n) for n in nodes]))

    assets_dump = os.path.join(os.path.dirname(dump_path), "node_assets.txt")

    def ids(static, key):
        return list(static) + [i for i in ng.discover(spec["token"], spec["suffix"][key], assets_dump)
                               if i not in static]

    def tex_node(fname, raw):
        node, _ = ng.add_node(graph, ids(spec["image_ids"], "image"))
        if node is None:
            return None
        fp = os.path.join(base, "textures", fname)
        p = ng.find_port(node, "in", spec["path_port"])
        if p is not None:
            target = (ng.child_port(p, spec["path_child"]) if spec["path_child"] else None) or p
            ng.set_value(target, maxon.Url(fp), fp, maxon.Url("file:///" + fp.replace("\\", "/")))
            cs = None
            if SET_COLORSPACE:
                cs = ng.child_port(p, "colorspace") if spec["path_child"] else None
                if cs is None and spec["cs_port"]:
                    cs = ng.find_port(node, "in", spec["cs_port"])
            if cs is not None:
                ng.set_value(cs, *(("Raw", "raw") if raw else ("Auto", "auto")))
        else:
            warns.append("texture path port not found")
        out = ng.find_port(node, "out", spec["image_out"])
        if out is None:
            outs = ng.ports(node, "out")
            out = outs[0][1] if outs else None
        return out

    def const(port, v):
        if isinstance(v, list) and len(v) >= 3:
            return ng.set_value(port, maxon.Color(v[0], v[1], v[2]), maxon.Vector(v[0], v[1], v[2]))
        if isinstance(v, list):
            v = v[0]
        return ng.set_value(port, float(v))

    connected = 0
    pm = spec["ports"]
    with graph.BeginTransaction() as tr:
        if mode == "openpbr":
            new, _nid = ng.add_node(graph, list(spec["openpbr_ids"]) +
                                    ng.discover(spec["token"], spec["openpbr_suffixes"], assets_dump))
            if new is None:
                raise RuntimeError("OpenPBR node not available")
            new_out = (ng.ports(new, "out") or [(0, None)])[0][1]
            out_in = None
            for n in nodes:
                if n is surf:
                    continue
                out_in = ng.find_port(n, "in", ["surface"])
                if out_in is not None:
                    break
            if new_out is None or out_in is None:
                raise RuntimeError("could not wire OpenPBR to the material output")
            try:
                surf.Remove()
            except Exception as e:  # noqa
                _log.log("old surface node not removed: %r" % (e,))
            ng.connect(new_out, out_in)
            surf = new
            pm = spec["openpbr_ports"]
        for key in ("color", "roughness", "metallic", "alpha", "emission", "transmission"):
            dst = ng.find_port(surf, "in", pm[key])
            ch = channels.get(key)
            if dst is None:
                if ch or key in values:
                    warns.append("%s: surface port not found" % key)
                continue
            if ch:
                out = tex_node(ch["file"], key != "color" and key != "emission")
                if out is not None and ng.connect(out, dst):
                    connected += 1
                    if key == "emission":
                        w = ng.find_port(surf, "in", pm["emission_weight"])
                        if w is not None:
                            ng.set_value(w, 1.0)
            elif key in values:
                const(dst, values[key])
        if "ior" in values:
            p = ng.find_port(surf, "in", pm["ior"])
            if p is not None:
                ng.set_value(p, float(values["ior"]))
        if "emission_strength" in values and "emission" in values:
            w = ng.find_port(surf, "in", pm["emission_weight"])
            if w is not None:
                ng.set_value(w, float(values["emission_strength"]))
        for key, hids, inp, typ in (("normal", ids(spec["normal_ids"], "normal"), spec["normal_in"], spec["normal_type"]),
                                    ("bump", ids(spec["bump_ids"], "bump"), spec["bump_in"], spec["bump_type"])):
            ch = channels.get(key)
            if not ch:
                continue
            dst = ng.find_port(surf, "in", pm["normal"])
            helper, _ = ng.add_node(graph, hids)
            img_out = tex_node(ch["file"], True)
            if dst is None or helper is None or img_out is None:
                warns.append("%s map could not be connected" % key)
                continue
            hin = ng.find_port(helper, "in", inp)
            hout = ng.find_port(helper, "out", spec["normal_out"]) or (ng.ports(helper, "out") or [(0, None)])[0][1]
            if typ is not None:
                tp = ng.find_port(helper, "in", ["inputtype", "input_type"])
                if tp is not None:
                    ng.set_value(tp, typ)
            if hin is not None and hout is not None and ng.connect(img_out, hin) and ng.connect(hout, dst):
                connected += 1
        tr.Commit()
    if channels.get("displacement"):
        warns.append("displacement map not connected (node materials)")
    if channels and connected == 0:
        raise RuntimeError("no texture could be connected (see graph_dump.txt)")
    return mat, warns


# --------------------------------------------------------------- classic
def _set_cycle(obj, names, picker):
    try:
        for bc, pid, gid in obj.GetDescription(c4d.DESCFLAGS_DESC_0):
            if (bc[c4d.DESC_NAME] or "").strip().lower() not in names or pid[0].dtype != c4d.DTYPE_LONG:
                continue
            cyc = bc[c4d.DESC_CYCLE]
            for idx, label in (cyc or []):
                if label and picker(str(label).lower()):
                    obj[pid] = idx
                    return True
    except Exception:
        pass
    return False


def set_shader_cs(shd, mode):
    """Bitmap shader colour space: mode 'auto' (colour maps) or 'raw' (normal, roughness, ... maps)."""
    want = mode.lower()
    doc = c4d.documents.GetActiveDocument()
    pid = getattr(c4d, "BITMAPSHADER_OCIO_INPUT_COLORSPACE", None)
    if pid is not None:
        try:                                              # A: document name -> id lookup
            v = doc.GetColorSpaceIdFromName(pid, want.capitalize())
            if v != c4d.NOTOK:
                shd[pid] = v
                if shd[pid] == v:
                    return True
        except Exception as e:  # noqa
            _log.log("colour space lookup: %r" % (e,))
        try:                                              # B: the parameter's own cycle list
            desc = shd.GetDescription(c4d.DESCFLAGS_DESC_0)
            bc = desc.GetParameter(c4d.DescID(c4d.DescLevel(pid)))
            cyc = [(k, str(v)) for k, v in bc[c4d.DESC_CYCLE]]
            for k, label in cyc:
                if label.strip().lower() == want:
                    shd[pid] = k
                    return True
            for k, label in cyc:
                if label.strip().lower().startswith(want):
                    shd[pid] = k
                    return True
            _log.log("colour space '%s' not in cycle: %s" % (want, [l for _, l in cyc][:20]))
        except Exception as e:  # noqa
            _log.log("colour space cycle: %r" % (e,))
    names = ("color space", "colorspace", "color profile", "colour space")
    ok = _set_cycle(shd, names, lambda l: l.strip().startswith(want) or (want == "raw" and "non-color" in l))
    if not ok:
        _log.log("colour space '%s' could not be set on the bitmap shader" % want)
    return ok


def bitmap_shader(path, raw=False):
    sh = c4d.BaseShader(c4d.Xbitmap)
    sh[c4d.BITMAPSHADER_FILENAME] = path
    if SET_COLORSPACE:
        set_shader_cs(sh, "raw" if raw else "auto")
    return sh


def _classic(name, manifest, base):
    ch = manifest.get("channels", {})
    vals = manifest.get("values", {})
    warns = []
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)

    def tex(key, raw):
        c = ch.get(key)
        if not c:
            return None
        sh = bitmap_shader(os.path.join(base, "textures", c["file"]), raw)
        mat.InsertShader(sh)
        return sh

    sh = tex("color", False)
    if sh:
        mat[c4d.MATERIAL_USE_COLOR] = True
        mat[c4d.MATERIAL_COLOR_SHADER] = sh
    elif isinstance(vals.get("color"), list):
        v = vals["color"]
        mat[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(v[0], v[1], v[2])
    try:
        mat[c4d.MATERIAL_USE_REFLECTION] = True
        lid = mat.GetReflectionLayerIndex(0).GetDataID()
        mat[lid + c4d.REFLECTION_LAYER_MAIN_DISTRIBUTION] = c4d.REFLECTION_DISTRIBUTION_GGX
        rs = tex("roughness", True)
        if rs:
            mat[lid + c4d.REFLECTION_LAYER_MAIN_SHADER_ROUGHNESS] = rs
        elif isinstance(vals.get("roughness"), float):
            mat[lid + c4d.REFLECTION_LAYER_MAIN_VALUE_ROUGHNESS] = vals["roughness"]
    except Exception as e:  # noqa
        warns.append("reflection setup failed: %r" % (e,))
    t = vals.get("transmission")
    if isinstance(t, float) and t > 0.3:
        try:
            mat[c4d.MATERIAL_USE_TRANSPARENCY] = True
            mat[c4d.MATERIAL_TRANSPARENCY_BRIGHTNESS] = min(1.0, t)
            mat[c4d.MATERIAL_TRANSPARENCY_REFRACTION] = float(vals.get("ior", 1.45))
        except Exception as e:  # noqa
            warns.append("transparency failed: %r" % (e,))
    for key, use, slot, raw in (("normal", c4d.MATERIAL_USE_NORMAL, c4d.MATERIAL_NORMAL_SHADER, True),
                                ("bump", c4d.MATERIAL_USE_BUMP, c4d.MATERIAL_BUMP_SHADER, True),
                                ("displacement", c4d.MATERIAL_USE_DISPLACEMENT, c4d.MATERIAL_DISPLACEMENT_SHADER, True),
                                ("alpha", c4d.MATERIAL_USE_ALPHA, c4d.MATERIAL_ALPHA_SHADER, True),
                                ("emission", c4d.MATERIAL_USE_LUMINANCE, c4d.MATERIAL_LUMINANCE_SHADER, False)):
        s = tex(key, raw)
        if s:
            mat[use] = True
            mat[slot] = s
    if "metallic" in ch:
        warns.append("metallic map is not mapped in the Standard material")
    return mat, warns


# --------------------------------------------------------------- Arnold: use Arnold's own converter
def _find_cmds(groups, exclude=()):
    try:
        plugs = list(c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_COMMAND, True))
    except Exception:
        return []
    for words in groups:
        out = [p for p in plugs
               if all(w in (p.GetName() or "").lower() for w in words)
               and not any(x in (p.GetName() or "").lower() for x in exclude)]
        if out:
            return out
    return []


def _guid(o):
    try:
        g = o.GetGUID()
        return g if isinstance(g, (int, bytes)) else bytes(g)
    except Exception:
        return id(o)


def _all_materials(doc):
    out, m = [], doc.GetFirstMaterial()
    while m:
        out.append(m)
        m = m.GetNext()
    return out


def _locate(doc, original, name, before):
    act = doc.GetActiveMaterial()
    if act is not None and (act.GetName() == name or name in act.GetName()):
        return act
    mats = _all_materials(doc)
    new = [m for m in mats if _guid(m) not in before and (m.GetName() == name or name in m.GetName())]
    if new:
        return new[0]
    same = [m for m in mats if m.GetName() == name]
    return same[0] if same else original


def arnold_convert(doc, mat):
    """Run Arnold's own 'Convert Selected C4D Materials to Arnold Materials' (+ OpenPBR conversion).
    Returns (material, notes, used) where used is arnold-openpbr / arnold-converted / c4d."""
    notes = []
    name = mat.GetName()
    cmds = _find_cmds([["convert", "selected", "c4d", "arnold"], ["convert", "c4d", "arnold", "materials"]],
                      exclude=("copy",))
    if not cmds:
        _log.log("Arnold convert command not found")
        return mat, ["Arnold's material converter was not found (Arnold menu > Utilities > Material > Convert)"], "c4d"
    before = set(_guid(m) for m in _all_materials(doc))
    try:
        doc.SetActiveMaterial(mat, c4d.SELECTION_NEW)
        _log.log("running command: %s" % cmds[0].GetName())
        c4d.CallCommand(cmds[0].GetID())
        c4d.EventAdd()
    except Exception as e:  # noqa
        _log.log("Arnold convert failed: %r" % (e,))
        return mat, ["Arnold conversion failed: %s" % e], "c4d"
    res = _locate(doc, mat, name, before)
    used = "arnold-converted"
    ocmds = _find_cmds([["openpbr", "selected", "arnold"], ["convert", "openpbr", "selected"]])
    if ocmds:
        try:
            doc.SetActiveMaterial(res, c4d.SELECTION_NEW)
            _log.log("running command: %s" % ocmds[0].GetName())
            c4d.CallCommand(ocmds[0].GetID())
            c4d.EventAdd()
            res = _locate(doc, res, name, before)
            used = "arnold-openpbr"
        except Exception as e:  # noqa
            _log.log("OpenPBR conversion failed: %r" % (e,))
            notes.append("OpenPBR conversion failed, material stays Standard Surface")
    else:
        notes.append("OpenPBR converter command not found, material stays Standard Surface")
    return res, notes, used


ENGINE_CONVERT_CMDS = {
    "octane": [["convert", "octane"], ["octane", "convert"], ["c4d", "octane", "material"]],
    "corona": [["convert", "corona"], ["corona", "convert"], ["c4d", "corona", "material"]],
    "vray": [["convert", "v-ray"], ["convert", "vray"], ["v-ray", "convert"], ["vray", "convert"]],
}
ENGINE_LABEL = {"octane": "Octane", "corona": "Corona", "vray": "V-Ray"}


def convert_for_engine(doc, mat, engine):
    """Octane / Corona / V-Ray: run the renderer's own material converter on the new C4D material.
    Returns (material, notes, used)."""
    label = ENGINE_LABEL.get(engine, engine)
    name = mat.GetName()
    cmds = _find_cmds(ENGINE_CONVERT_CMDS.get(engine, []), exclude=("copy",))
    if not cmds:
        _log.log("%s converter command not found" % label)
        return mat, ["%s converter command not found: created a C4D Standard material "
                     "(convert it with %s's own converter)" % (label, label)], "c4d"
    before = set(_guid(m) for m in _all_materials(doc))
    try:
        doc.SetActiveMaterial(mat, c4d.SELECTION_NEW)
        _log.log("running command: %s" % cmds[0].GetName())
        c4d.CallCommand(cmds[0].GetID())
        c4d.EventAdd()
    except Exception as e:  # noqa
        _log.log("%s convert failed: %r" % (label, e))
        return mat, ["%s conversion failed: %s" % (label, e)], "c4d"
    return _locate(doc, mat, name, before), [], engine + "-converted"


def finalize_material(doc, mat, engine):
    if engine == "arnold":
        return arnold_convert(doc, mat)
    return convert_for_engine(doc, mat, engine)


def build_material(name, manifest, base, engine, dump_path):
    """Returns (material, warnings, used). used: arnold-classic (needs arnold_convert) /
    redshift-openpbr / redshift-standard / c4d."""
    warns = []
    if engine in CONVERT_ENGINES:
        mat, w = _classic(name, manifest, base)
        return mat, w, engine + "-classic"
    spec = SPECS.get(engine)
    if spec:
        last = ""
        for mode in ("openpbr", "standard"):
            try:
                mat, w = _build_node_material(name, manifest, base, spec, dump_path, mode)
                if mode == "standard":
                    warns.append("OpenPBR unavailable, used %s Standard" % spec["name"])
                return mat, warns + w, "%s-%s" % (engine, mode)
            except Exception as e:  # noqa
                _log.log("%s %s material failed: %r" % (spec["name"], mode, e))
                last = str(e)[:90]
        warns.append("%s node material failed (%s), used a Standard material" % (spec["name"], last))
    mat, w = _classic(name, manifest, base)
    return mat, warns + w, "c4d"
