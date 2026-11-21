# -*- coding: utf-8 -*-
"""Main-thread only: builds scene content in Cinema 4D from prepared results."""
import json
import os
import re

import c4d

from . import log as _log
from . import hdri_build, materials


# ----------------------------------------------------------------- helpers
def _desc_items(obj):
    try:
        for bc, pid, gid in obj.GetDescription(c4d.DESCFLAGS_DESC_0):
            yield bc, pid
    except Exception as e:  # noqa
        _log.log("description scan failed: %r" % (e,))


def _param_name(bc):
    try:
        return (bc[c4d.DESC_NAME] or "").strip()
    except Exception:
        return ""


def _set_cycle_by_label(obj, param_names, picker):
    for bc, pid in _desc_items(obj):
        if _param_name(bc).lower() not in param_names:
            continue
        try:
            if pid[0].dtype != c4d.DTYPE_LONG:
                continue
            for idx, label in (bc[c4d.DESC_CYCLE] or []):
                if label and picker(str(label).lower()):
                    obj[pid] = idx
                    return True
        except Exception:
            continue
    return False


_CS_NAMES = ("color space", "colorspace", "color profile", "colour space", "texture color space")


def _set_linear(obj):
    return _set_cycle_by_label(obj, _CS_NAMES, lambda l: "linear" in l and "srgb" in l)


def _hdr_shader(path):
    sh = c4d.BaseShader(c4d.Xbitmap)
    sh[c4d.BITMAPSHADER_FILENAME] = path
    _set_linear(sh)
    return sh


def _params_of_type(obj, dtypes):
    out = []
    for bc, pid in _desc_items(obj):
        try:
            if pid[0].dtype in dtypes:
                out.append((_param_name(bc), pid))
        except Exception:
            continue
    return out


def _plugins(match):
    out = []
    try:
        for p in c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_OBJECT, True):
            n = p.GetName() or ""
            if match(n.lower()):
                out.append((p.GetID(), n))
    except Exception as e:  # noqa
        _log.log("plugin scan failed: %r" % (e,))
    return out


def _insert(doc, obj):
    doc.StartUndo()
    doc.InsertObject(obj)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, obj)
    doc.SetActiveObject(obj, c4d.SELECTION_NEW)
    doc.EndUndo()


# ----------------------------------------------------------------- HDRI
def _c4d_sky(doc, path, name):
    sky = c4d.BaseObject(c4d.Osky)
    sky.SetName(name)
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    try:
        mat[c4d.MATERIAL_USE_COLOR] = False
        mat[c4d.MATERIAL_USE_REFLECTION] = False
    except Exception:
        pass
    mat[c4d.MATERIAL_USE_LUMINANCE] = True
    sh = _hdr_shader(path)
    mat[c4d.MATERIAL_LUMINANCE_SHADER] = sh
    mat.InsertShader(sh)
    doc.InsertMaterial(mat)
    sky.MakeTag(c4d.Ttexture)[c4d.TEXTURETAG_MATERIAL] = mat
    _insert(doc, sky)
    return sky


def _configure_arnold(obj, path):
    _set_cycle_by_label(obj, ("type", "light type"), lambda l: "sky" in l and "physical" not in l)
    sh = _hdr_shader(path)
    links = _params_of_type(obj, (c4d.DTYPE_BASELISTLINK,))
    slot = next((p for n, p in links if n.lower() == "color"), None)
    if slot is None:
        _log.log("Arnold: no 'Color' link param; link params: %s" % [(n, p[0].id) for n, p in links])
        slot = next((p for n, p in links if "color" in n.lower() or "texture" in n.lower()), None)
    if slot is None:
        return False
    obj[slot] = sh
    obj.InsertShader(sh)
    _set_linear(obj)
    return True


def _configure_redshift(obj, path):
    _set_cycle_by_label(obj, ("type", "light type"), lambda l: "dome" in l)
    fparams = _params_of_type(obj, (c4d.DTYPE_FILENAME,))
    target = next((p for n, p in fparams
                   if n.lower() in ("texture", "dome texture", "tex", "file", "path", "filename")), None)
    if target is None and fparams:
        target = fparams[0][1]
    if target is not None:
        obj[target] = path
        return True
    links = _params_of_type(obj, (c4d.DTYPE_BASELISTLINK,))
    for n, p in links:
        if "texture" in n.lower() or "color" in n.lower():
            sh = _hdr_shader(path)
            obj[p] = sh
            obj.InsertShader(sh)
            return True
    _log.log("Redshift: no texture parameter; filename params=%s link params=%s"
             % ([(n, p[0].id) for n, p in fparams], [(n, p[0].id) for n, p in links]))
    return False


def _from_object_plugins(doc, cands, name, configure, path):
    for pid, pname in cands:
        try:
            obj = c4d.BaseObject(pid)
            if obj is None:
                continue
            obj.SetName(name)
            if configure(obj, path):
                _insert(doc, obj)
                return obj
        except Exception as e:  # noqa
            _log.log("candidate %s failed: %r" % (pname, e))
    return None


def _from_commands(doc, match, name, configure, path):
    """Fallback: run the renderer's own 'create' menu command, then configure the new active object."""
    try:
        cmds = [(p.GetID(), p.GetName() or "") for p in c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_COMMAND, True)
                if match((p.GetName() or "").lower())]
    except Exception as e:  # noqa
        _log.log("command scan failed: %r" % (e,))
        return None
    _log.log("command candidates: %s" % cmds)
    for cid, cname in cmds[:4]:
        try:
            before = doc.GetActiveObject()
            c4d.CallCommand(cid)
            obj = doc.GetActiveObject()
            if obj is None or obj == before:
                continue
            obj.SetName(name)
            if configure(obj, path):
                return obj
        except Exception as e:  # noqa
            _log.log("command %s failed: %r" % (cname, e))
    return None


def _arnold_sky(doc, path, name):
    cands = _plugins(lambda n: "arnold" in n and ("sky" in n or "light" in n))
    _log.log("Arnold object candidates: %s" % cands)
    cands.sort(key=lambda c: 0 if "skydome" in c[1].lower() else 1 if "sky" in c[1].lower() else 2)
    obj = _from_object_plugins(doc, cands, name, _configure_arnold, path)
    if obj is None:
        obj = _from_commands(doc, lambda n: "arnold" in n and "sky" in n, name, _configure_arnold, path)
    return obj


def _redshift_dome(doc, path, name):
    cands = _plugins(lambda n: ("redshift" in n or n.startswith("rs ")) and ("light" in n or "dome" in n))
    _log.log("Redshift object candidates: %s" % cands)
    cands.sort(key=lambda c: 0 if "dome" in c[1].lower() else 1)
    obj = _from_object_plugins(doc, cands, name, _configure_redshift, path)
    if obj is None:
        obj = _from_commands(doc, lambda n: ("redshift" in n or n.startswith("rs ")) and "dome" in n,
                             name, _configure_redshift, path)
    return obj


def import_hdri(doc, path, name, engine):
    """Uses the builders ported from the working Poly Haven plugin (errors propagate to the dialog)."""
    msg = hdri_build.build_hdri(engine, doc, path, name)
    c4d.EventAdd()
    return msg


# ----------------------------------------------------------------- model
def _guid(o):
    """Stable id of a scene element, or None when Cinema 4D can't give one."""
    for getter in ("GetGUID", "GetMarker"):
        fn = getattr(o, getter, None)
        if fn is None:
            continue
        try:
            g = fn()
            if g is not None:
                return g if isinstance(g, (int, bytes)) else bytes(g)
        except Exception:
            pass
    return None


def _top_guids(doc):
    out, o = set(), doc.GetFirstObject()
    while o:
        out.add(_guid(o))
        o = o.GetNext()
    return out


def _mat_guids(doc):
    out, m = set(), doc.GetFirstMaterial()
    while m:
        out.add(_guid(m))
        m = m.GetNext()
    return out


def top_guids(doc):
    return _top_guids(doc)


def mat_guids(doc):
    return _mat_guids(doc)


def doc_id(doc):
    try:
        return (doc.GetDocumentName(), doc.GetDocumentPath())
    except Exception:
        return None


def same_doc(doc, job):
    """True when *doc* is the document the drag started in."""
    try:
        if doc == job["doc"]:
            return True
    except Exception:
        pass
    ident = job.get("docid")
    return ident is not None and ident == doc_id(doc)


def dropped_roots(doc, before):
    """Top-level objects that appeared since *before* (a drop snapshot).

    Only what the drop added is returned. If the snapshot can't be trusted (no stable ids, or none
    of the objects that were in the scene are found any more) nothing is returned, so existing
    objects are never removed.
    """
    if None in before:
        return []
    tops, o = [], doc.GetFirstObject()
    while o:
        tops.append(o)
        o = o.GetNext()
    guids = [_guid(t) for t in tops]
    if None in guids:
        return []
    if before and not any(g in before for g in guids):
        return []
    return [t for t, g in zip(tops, guids) if g not in before]


def _walk(obj):
    while obj:
        yield obj
        for c in _walk(obj.GetDown()):
            yield c
        obj = obj.GetNext()


def _norm(n):
    return re.sub(r"\.\d{3}$", "", (n or "").replace("Material::", "").strip())


def _apply_model_materials(doc, roots, index_path, engine, dump_path, mats_before):
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)
    built, scales, warns = {}, {}, []
    for mname, info in index.get("materials", {}).items():
        mdir = info["dir"]
        try:
            with open(os.path.join(mdir, "manifest.json"), "r", encoding="utf-8") as f:
                man = json.load(f)
            mat, w, used = materials.build_material(mname, man, mdir, engine, dump_path)
            doc.InsertMaterial(mat)
            doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)
            if used.endswith("-classic"):
                mat, notes, _u = materials.finalize_material(doc, mat, engine)
                w = list(w) + notes
            built[mname] = mat
            scales[mname] = man.get("uv_scale", [1, 1])
            warns += w
        except Exception as e:  # noqa
            _log.log("material %s failed: %r" % (mname, e))
            warns.append("material %s failed" % mname)

    def lookup(n):
        if n in built:
            return n
        nn = _norm(n)
        for k in built:
            if k == nn or _norm(k) == nn:
                return k
        for k in built:
            if nn and (nn in k or k in nn):
                return k
        return None

    replaced, assigned = 0, 0
    for root in roots:
        for obj in _walk(root):
            tags = [t for t in obj.GetTags() if t.CheckType(c4d.Ttexture)]
            had = False
            for t in tags:
                m = t[c4d.TEXTURETAG_MATERIAL]
                key = lookup(m.GetName()) if m else None
                if key:
                    t[c4d.TEXTURETAG_MATERIAL] = built[key]
                    sx, sy = (scales.get(key) or [1, 1])[:2]
                    try:
                        t[c4d.TEXTURETAG_TILESX], t[c4d.TEXTURETAG_TILESY] = float(sx), float(sy)
                    except Exception:
                        pass
                    replaced += 1
                    had = True
            if not had and not tags:
                names = index.get("objects", {}).get(obj.GetName()) or index.get("objects", {}).get(_norm(obj.GetName()))
                key = lookup(names[0]) if names else None
                if key and obj.CheckType(c4d.Opolygon):
                    tag = obj.MakeTag(c4d.Ttexture)
                    tag[c4d.TEXTURETAG_MATERIAL] = built[key]
                    tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW
                    assigned += 1
    # remove the materials the FBX importer created
    m = doc.GetFirstMaterial()
    stale = []
    while m:
        if _guid(m) not in mats_before and m not in built.values():
            stale.append(m)
        m = m.GetNext()
    for m in stale:
        try:
            m.Remove()
        except Exception:
            pass
    return "%d material(s) built, %d tag(s) updated, %d assigned" % (len(built), replaced, assigned), warns


def import_model(doc, path, name, index_path, engine, dump_path, label="Model",
                 mats_before=None):
    before = _top_guids(doc)
    if mats_before is None:
        mats_before = _mat_guids(doc)
    flags = c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS | c4d.SCENEFILTER_MERGESCENE
    if not c4d.documents.MergeDocument(doc, path, flags, None):
        raise RuntimeError("Cinema 4D could not import %s" % os.path.basename(path))
    new, o = [], doc.GetFirstObject()
    while o:
        if _guid(o) not in before:
            new.append(o)
        o = o.GetNext()
    msg = "%s '%s' imported (%d top-level objects)" % (label, name, len(new))
    if new:
        null = c4d.BaseObject(c4d.Onull)
        null.SetName(name)
        doc.InsertObject(null)
        for o in new:
            o.Remove()
            o.InsertUnder(null)
        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, null)
        if index_path and os.path.isfile(index_path):
            try:
                info, warns = _apply_model_materials(doc, [null], index_path, engine, dump_path, mats_before)
                msg += ", " + info
                if warns:
                    msg += ". " + "; ".join(warns[:2])
            except Exception as e:  # noqa
                _log.log("model materials failed: %r" % (e,))
                msg += ". Materials failed: %s" % e
        doc.EndUndo()
        doc.SetActiveObject(null, c4d.SELECTION_NEW)
    c4d.EventAdd()
    return msg


def finish_drop(doc, roots, name, path, index_path, engine, dump_path, mats_before,
                label="Model"):
    """Replace the objects Cinema 4D created for a dropped file with our own import.

    Cinema 4D's drop handler adds the geometry without our rebuilt materials, so the
    dropped objects are removed and the file is merged again through
    :func:`import_model` (the double-click path). *mats_before* is the material
    snapshot taken before the drag, so the importer's own materials are cleaned up.
    """
    if not path or not os.path.isfile(path):
        return "Imported, but the saved file is missing."
    doc.StartUndo()
    for o in roots:
        try:
            doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, o)
            o.Remove()
        except Exception as e:  # noqa
            _log.log("drop: cannot remove '%s': %r" % (o.GetName(), e))
    doc.EndUndo()
    try:
        return import_model(doc, path, name, index_path, engine, dump_path,
                            label=label, mats_before=mats_before)
    except Exception as e:  # noqa
        _log.log("drop import failed: %r" % (e,))
        return "Imported, but the materials failed: %s" % e


# ----------------------------------------------------------------- material
def import_material(doc, manifest_dir, name, engine, apply_to_selection, dump_path):
    with open(os.path.join(manifest_dir, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    mat, warns, used = materials.build_material(name, manifest, manifest_dir, engine, dump_path)
    doc.StartUndo()
    doc.InsertMaterial(mat)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)
    if used.endswith("-classic"):
        mat, notes, used = materials.finalize_material(doc, mat, engine)
        warns = list(warns) + notes
    applied = 0
    if apply_to_selection:
        sx, sy = manifest.get("uv_scale", [1, 1])[:2]
        for obj in doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN) or []:
            tag = obj.MakeTag(c4d.Ttexture)
            if tag is None:
                continue
            tag[c4d.TEXTURETAG_MATERIAL] = mat
            tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW
            try:
                tag[c4d.TEXTURETAG_TILESX] = float(sx)
                tag[c4d.TEXTURETAG_TILESY] = float(sy)
            except Exception:
                pass
            doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, tag)
            applied += 1
    doc.EndUndo()
    c4d.EventAdd()
    label = {"arnold-openpbr": "Arnold OpenPBR", "arnold-standard": "Arnold Standard Surface", "arnold-converted": "Arnold (converted)",
             "redshift-openpbr": "Redshift OpenPBR", "redshift-standard": "Redshift Standard",
             "octane-converted": "Octane (converted)", "corona-converted": "Corona (converted)",
             "vray-converted": "V-Ray (converted)", "c4d": "C4D Standard"}.get(used, used)
    msg = "Material '%s' created (%s)" % (name, label)
    if applied:
        msg += ", applied to %d object(s)" % applied
    if warns:
        msg += ". " + "; ".join(warns[:2])
    return msg


def import_result(doc, asset, result, settings):
    engine = settings.get("renderer") or "arnold"
    dump_path = os.path.join(settings.dir, "graph_dump.txt")
    kind = result.get("kind")
    if kind == "hdri":
        return import_hdri(doc, result["path"], asset.name, engine)
    if kind == "model":
        return import_model(doc, result["path"], asset.name, result.get("materials_index", ""), engine, dump_path,
                            "Scene" if result.get("is_scene") else "Model")
    if kind == "material":
        return import_material(doc, result["dir"], asset.name, engine,
                               bool(settings.get("apply_to_selection")), dump_path)
    raise RuntimeError("Unknown result kind: %s" % kind)
