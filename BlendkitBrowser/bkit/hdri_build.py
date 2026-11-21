# -*- coding: utf-8 -*-
"""HDRI scene builders, ported 1:1 from the working Poly Haven HDRI Browser plugin
(Arnold via arnold.custom_gui, Redshift RS Light dome, C4D Sky with OCIO linear colour space)."""
import os
import sys

import c4d

ARNOLD_SKY_COLOR = 268620635          # C4DAIP_SKYDOME_LIGHT_COLOR (C4DtoA docs)


class _P:
    @staticmethod
    def print(*a):
        from . import log as _log
        _log.log(" ".join(str(x) for x in a))


def _key(o):
    try:
        return o.GetGUID()
    except Exception:
        return (o.GetType(), o.GetName())


def iter_objects(doc):
    stack = [doc.GetFirstObject()]
    while stack:
        o = stack.pop()
        while o:
            yield o
            d = o.GetDown()
            if d:
                stack.append(d)
            o = o.GetNext()


def snapshot(doc):
    objs, tags = set(), set()
    for o in iter_objects(doc):
        objs.add(_key(o))
        for t in o.GetTags():
            tags.add(_key(t))
    return objs, tags


def run_command(doc, cid):
    """Execute a menu command; return (new objects, new tags)."""
    b_o, b_t = snapshot(doc)
    c4d.CallCommand(cid)
    new_o, new_t = [], []
    for o in iter_objects(doc):
        if _key(o) not in b_o:
            new_o.append(o)
        for t in o.GetTags():
            if _key(t) not in b_t:
                new_t.append(t)
    return new_o, new_t


def find_commands(*groups):
    """Find command plugins; groups are tried in priority order, a group
    matches when all of its words are in the command name."""
    plugs = list(c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_COMMAND, True))
    for words in groups:
        res = [p for p in plugs if all(w in p.GetName().lower() for w in words)]
        if res:
            res.sort(key=lambda p: 0 if "light" in p.GetName().lower() else 1)
            return res
    return []


def dump_commands(*words):
    print("[HDRI] commands matching %s:" % (words,))
    for p in c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_COMMAND, True):
        n = p.GetName().lower()
        if any(w in n for w in words):
            print("   %d  %s" % (p.GetID(), p.GetName()))


def _params(owner, dtypes):
    out = []
    try:
        desc = owner.GetDescription(c4d.DESCFLAGS_DESC_0)
        for bc, pid, gid in desc:
            try:
                if pid.GetDepth() != 1:
                    continue
                lvl = pid[0]
                if lvl.dtype not in dtypes:
                    continue
                name = str(bc[c4d.DESC_NAME] or bc[c4d.DESC_SHORT_NAME] or "").lower()
                out.append((lvl.id, name))
            except Exception:
                continue
    except Exception:
        pass
    return out


def dump_params(owner):
    print("[HDRI] parameters of '%s' (type %s):" % (owner.GetName(), owner.GetType()))
    for pid, name in _params(owner, (c4d.DTYPE_BASELISTLINK, c4d.DTYPE_FILENAME, c4d.DTYPE_STRING)):
        print("   id %s  %s" % (pid, name))


def set_filename_param(owner, path):
    cands = _params(owner, (c4d.DTYPE_FILENAME,))
    cands.sort(key=lambda c: 0 if any(h in c[1] for h in ("file", "path", "image", "hdr", "texture")) else 1)
    for pid, name in cands:
        try:
            owner[pid] = path
            return name
        except Exception:
            pass
    return None


_cs_info = [""]


def set_linear_colorspace(shd):
    """Bitmap shader input colour space -> linear sRGB (scene-linear Rec.709-sRGB).
    Returns True when it was really set; details of a failure go to _cs_info."""
    info = []
    _cs_info[0] = ""
    if shd is None:
        return False
    try:
        if shd.GetType() != c4d.Xbitmap:
            return False
    except Exception:
        return False
    doc = None
    try:
        doc = shd.GetDocument()
    except Exception:
        pass
    doc = doc or c4d.documents.GetActiveDocument()
    ocio_mode = False
    try:
        ocio_mode = doc[c4d.DOCUMENT_COLOR_MANAGEMENT] == c4d.DOCUMENT_COLOR_MANAGEMENT_OCIO
    except Exception:
        pass

    ok = False
    pid = getattr(c4d, "BITMAPSHADER_OCIO_INPUT_COLORSPACE", None)
    if pid is not None and ocio_mode:
        names = []
        try:
            names = list(doc.GetOcioColorSpaceNames())
        except Exception as e:
            info.append("GetOcioColorSpaceNames: %s" % e)
        order = []
        for test in (lambda n: "linear srgb" in n and "scene-linear rec.709-srgb" in n,
                     lambda n: n == "scene-linear rec.709-srgb",
                     lambda n: "scene-linear rec.709-srgb" in n,
                     lambda n: "linear" in n and "rec.709" in n and "srgb" in n):
            for n in names:
                if test(n.lower()) and n not in order:
                    order.append(n)
        order += ["scene-linear Rec.709-sRGB", "linear sRGB (scene-linear Rec.709-sRGB)"]
        # method A: document name -> id lookup
        for n in order:
            try:
                v = doc.GetColorSpaceIdFromName(pid, n)
                if v != c4d.NOTOK:
                    shd[pid] = v
                    if shd[pid] == v:
                        ok = True
                        info.append("OCIO set via id lookup '%s'" % n)
                        break
            except Exception as e:
                info.append("lookup '%s': %s" % (n, e))
        # method B: the parameter's own cycle list
        if not ok:
            try:
                desc = shd.GetDescription(c4d.DESCFLAGS_DESC_0)
                bc = desc.GetParameter(c4d.DescID(c4d.DescLevel(pid)))
                cyc = [(k, str(v)) for k, v in bc[c4d.DESC_CYCLE]]
                for n in order:
                    for k, label in cyc:
                        if label.lower() == n.lower() or n.lower() in label.lower():
                            shd[pid] = k
                            ok = True
                            info.append("OCIO set via cycle '%s'" % label)
                            break
                    if ok:
                        break
                if not ok:
                    info.append("cycle labels: %s" % [l for _, l in cyc][:30])
            except Exception as e:
                info.append("cycle: %s" % e)
        if not ok:
            info.append("document colour spaces: %s" % names[:40])
    elif pid is None:
        info.append("no BITMAPSHADER_OCIO_INPUT_COLORSPACE in this C4D")

    try:                                         # classic colour management / extra safety
        if hasattr(c4d, "BITMAPSHADER_COLORPROFILE"):
            shd[c4d.BITMAPSHADER_COLORPROFILE] = c4d.BITMAPSHADER_COLORPROFILE_LINEAR
            if not ocio_mode:
                ok = True
                info.append("classic profile = Linear")
    except Exception:
        pass
    try:
        shd.Message(c4d.MSG_UPDATE)
    except Exception:
        pass
    _cs_info[0] = "; ".join(info)
    print("[HDRI] colour space: %s" % _cs_info[0])
    return ok




def build_c4d_sky(doc, path, aid):
    doc.StartUndo()
    sky = c4d.BaseObject(c4d.Osky)
    sky.SetName("HDRI " + aid)
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName("HDRI " + aid)
    mat[c4d.MATERIAL_USE_COLOR] = False
    mat[c4d.MATERIAL_USE_LUMINANCE] = True
    mat[c4d.MATERIAL_USE_REFLECTION] = False
    shd = c4d.BaseShader(c4d.Xbitmap)
    shd[c4d.BITMAPSHADER_FILENAME] = path
    mat[c4d.MATERIAL_LUMINANCE_SHADER] = shd
    mat.InsertShader(shd)
    set_linear_colorspace(shd)
    doc.InsertObject(sky)
    doc.InsertMaterial(mat)
    tag = sky.MakeTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_SPHERICAL
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, sky)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)
    doc.EndUndo()
    return "C4D Sky created"


def import_arnold_gui():
    """arnold.custom_gui lives in <C4D library>/scripts, which is not on sys.path
    inside plugins by default (see the C4DtoA developer's answer on the forum)."""
    try:
        import arnold.custom_gui as m
        return m
    except Exception:
        pass
    import importlib
    roots = []
    for nm in ("C4D_PATH_LIBRARY", "C4D_PATH_LIBRARY_USER"):
        if hasattr(c4d, nm):
            try:
                roots.append(os.path.join(c4d.storage.GeGetC4DPath(getattr(c4d, nm)), "scripts"))
            except Exception:
                pass
    try:
        roots.append(os.path.join(c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS), "library", "scripts"))
    except Exception:
        pass
    for r in roots:
        if os.path.isdir(os.path.join(r, "arnold")) and r not in sys.path:
            sys.path.append(r)
    importlib.invalidate_caches()
    try:
        import arnold.custom_gui as m
        return m
    except Exception as e:
        raise RuntimeError("cannot import arnold.custom_gui (%s); looked in: %s" % (e, "; ".join(roots)))


# The value C4DtoA itself stores when the "linear sRGB (scene-linear Rec.709-sRGB)" menu
# entry is chosen.
ARNOLD_LINEAR_CS = "linear sRGB"
_PENDING = []          # Arnold objects whose colour space is re-checked a moment later


def apply_arnold_cs(obj, cs, force=False):
    """Set ArnoldShaderLinkCustomData.texture_color_space (only that field)."""
    acg = import_arnold_gui()
    sl = acg.GetShaderLink(obj, ARNOLD_SKY_COLOR)
    if force or sl.texture_color_space != cs:
        sl.texture_color_space = cs
        acg.SetShaderLink(obj, ARNOLD_SKY_COLOR, sl)
    try:                                   # make other Arnold tools (Asset/Tx Manager) re-read the data
        obj.SetDirty(c4d.DIRTYFLAGS_DATA)
        obj.Message(c4d.MSG_UPDATE)
    except Exception:
        pass
    return acg.GetShaderLink(obj, ARNOLD_SKY_COLOR).texture_color_space


ARNOLD_SKY_TYPE = 1034624      # object type of an Arnold Sky in C4D 2027 / C4DtoA


def selected_arnold_sky(doc, acg):
    """The active object when it is an Arnold sky (so a new HDRI can be applied to it)."""
    obj = doc.GetActiveObject()
    if obj is None:
        return None
    if obj.GetType() != ARNOLD_SKY_TYPE and not obj.GetName().startswith("Arnold Skydome HDRI"):
        return None
    try:
        acg.GetShaderLink(obj, ARNOLD_SKY_COLOR)
    except Exception:
        return None
    return obj


def build_arnold(doc, path, aid):
    acg = import_arnold_gui()
    obj = selected_arnold_sky(doc, acg)          # an Arnold sky is selected -> reuse it
    reused = obj is not None
    if obj is None:
        cmds = find_commands(["skydome"], ["arnold", "sky"])
        if not cmds:
            dump_commands("arnold", "skydome")
            raise RuntimeError("Arnold skydome command not found (is C4DtoA installed?)")
        objs, _ = run_command(doc, cmds[0].GetID())
        if not objs:
            raise RuntimeError("the Arnold command created no object")
        obj = objs[0]
    else:
        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
    obj.SetName("Arnold Skydome HDRI " + aid)
    acg.SetShaderLink(obj, ARNOLD_SKY_COLOR, path)          # texture mode + file
    used, err = None, ""
    try:
        used = apply_arnold_cs(obj, ARNOLD_LINEAR_CS, force=True)   # linear sRGB
    except Exception as e:
        err = str(e)
        print("[HDRI] Arnold colour space error: %s" % e)
    if reused:
        doc.EndUndo()
    _PENDING.append({"obj": obj, "cs": ARNOLD_LINEAR_CS, "ticks": 0})   # re-check after Arnold's refresh
    obj.Message(c4d.MSG_UPDATE)
    c4d.EventAdd()
    info = ", colour space '%s'" % used if used else ", colour space NOT set: %s" % err[:120]
    return "Arnold sky %s (%s)%s" % ("updated - selected sky reused" if reused else "created",
                                     os.path.basename(path), info)


def build_redshift(doc, path, aid):
    RS_LIGHT = 1036751                           # Orslight (Maxon SDK forum)
    if not c4d.plugins.FindPlugin(RS_LIGHT, c4d.PLUGINTYPE_OBJECT):
        raise RuntimeError("Redshift light object not found (is Redshift installed?)")
    dome = getattr(c4d, "REDSHIFT_LIGHT_TYPE_DOME", 4)
    tex0 = getattr(c4d, "REDSHIFT_LIGHT_DOME_TEX0", 12000)
    fpath = getattr(c4d, "REDSHIFT_FILE_PATH", 1000)
    pid = c4d.DescID(
        c4d.DescLevel(tex0, 1036765, RS_LIGHT),  # "Texture" (unexposed datatype)
        c4d.DescLevel(fpath, c4d.DTYPE_STRING, 0))  # "Texture.Path"
    sel = doc.GetActiveObject()                  # a Redshift dome light is selected -> reuse it
    if sel is not None and sel.GetType() == RS_LIGHT and sel[c4d.REDSHIFT_LIGHT_TYPE] == dome:
        doc.StartUndo()
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, sel)
        sel[pid] = path
        sel.SetName("RS Dome Light " + aid)
        doc.EndUndo()
        return "Redshift RS Dome Light updated - selected light reused"
    light = c4d.BaseObject(RS_LIGHT)
    light[c4d.REDSHIFT_LIGHT_TYPE] = dome
    light[pid] = path
    light.SetName("RS Dome Light " + aid)
    doc.StartUndo()
    doc.InsertObject(light)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, light)
    doc.EndUndo()
    return "Redshift RS Dome Light created"




def pending_tick():
    """Call from the dialog timer: re-applies the Arnold colour space after Arnold's refresh."""
    for item in list(_PENDING):
        item["ticks"] += 1
        if item["ticks"] >= 2:
            _PENDING.remove(item)
            try:
                apply_arnold_cs(item["obj"], item["cs"])
                c4d.EventAdd()
            except Exception as e:
                print("[HDRI] colour space re-check: %s" % e)


# ---- generic builders for Octane / Corona / V-Ray (ported from the Poly Haven plugin)
def iter_shaders(owner):
    stack = [owner.GetFirstShader()]
    while stack:
        shd = stack.pop()
        while shd:
            yield shd
            d = shd.GetDown()
            if d:
                stack.append(d)
            shd = shd.GetNext()


def make_texture_shader(path, plugin_ids=()):
    for sid in plugin_ids:
        try:
            if c4d.plugins.FindPlugin(sid, c4d.PLUGINTYPE_SHADER):
                shd = c4d.BaseShader(sid)
                if shd and set_filename_param(shd, path):
                    return shd
        except Exception:
            pass
    shd = c4d.BaseShader(c4d.Xbitmap)
    shd[c4d.BITMAPSHADER_FILENAME] = path
    return shd


def link_texture(owner, shader, hints):
    cands = _params(owner, (c4d.DTYPE_BASELISTLINK,))
    ordered = []
    for h in hints:
        for c in cands:
            if h in c[1] and c not in ordered:
                ordered.append(c)
    if not ordered:
        return None
    try:
        owner.InsertShader(shader)
    except Exception:
        pass
    for pid, name in ordered:
        try:
            owner[pid] = shader
            if owner[pid] is not None:
                set_linear_colorspace(shader)
                return name
        except Exception:
            continue
    return None




def build_via_command(doc, path, aid, label, groups, keywords, hints, shader_ids=()):
    """Generic: run the engine's menu command, then plug the HDRI into the new
    object/tag by looking up its texture slot by name."""
    cmds = find_commands(*groups)
    if not cmds:
        dump_commands(*keywords)
        raise RuntimeError("%s command not found (is the renderer installed?)" % label)
    objs, tags = run_command(doc, cmds[0].GetID())
    owners = list(tags) + list(objs)
    if not owners:
        raise RuntimeError("the %s command created nothing (select an object first?)" % label)
    shader = make_texture_shader(path, shader_ids)
    for o in owners:
        if link_texture(o, shader, hints):
            return "%s created" % label
    for o in owners:
        if set_filename_param(o, path):
            return "%s created" % label
    for o in owners:
        dump_params(o)
    raise RuntimeError("%s was created but the texture slot was not found - see Console" % label)




def build_hdri(engine, doc, path, name):
    """Returns a status message. engine: arnold | redshift | octane | corona | vray | c4d"""
    if engine == "arnold":
        return build_arnold(doc, path, name)
    if engine == "redshift":
        return build_redshift(doc, path, name)
    if engine == "octane":
        return build_via_command(
            doc, path, name, "Octane HDRI Environment",
            [["hdri", "environment"], ["octane", "hdri"], ["texture", "environment"]],
            ("octane", "hdri", "environment"),
            ("texture", "hdri", "environment", "image", "map"),
            shader_ids=(1029508,))
    if engine == "corona":
        return build_via_command(
            doc, path, name, "Corona Sky", [["corona", "sky"]], ("corona",),
            ("texture", "hdri", "sky", "environment", "map", "color"))
    if engine == "vray":
        return build_via_command(
            doc, path, name, "V-Ray Dome Light",
            [["dome", "v-ray"], ["dome", "vray"], ["vray", "dome"]], ("vray", "v-ray", "dome"),
            ("texture", "hdri", "dome", "environment", "map", "color"))
    return build_c4d_sky(doc, path, name)
