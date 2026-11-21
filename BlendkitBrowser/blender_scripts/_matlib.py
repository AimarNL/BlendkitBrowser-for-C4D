"""Shared material extraction (runs inside Blender)."""
import json
import os
import re
import shutil

import bpy  # noqa

SKIP_INPUTS = {"Fac", "Factor", "Vector", "Strength", "Distance", "Scale", "Detail"}
EXT = {"PNG": ".png", "JPEG": ".jpg", "OPEN_EXR": ".exr", "TIFF": ".tif",
       "HDR": ".hdr", "TARGA": ".tga", "BMP": ".bmp"}


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:60] or "x"


CHANNEL_INDEX = {"red": 0, "r": 0, "green": 1, "g": 1, "blue": 2, "b": 2}


def find_image_ch(sock, depth=0, ch=None):
    """(image_node, channel_index_or_None). A Separate Color/RGB node on the way selects a channel."""
    if depth > 14 or not sock.is_linked:
        return None, None
    link = sock.links[0]
    node = link.from_node
    if node.type == "TEX_IMAGE":
        return (node, ch) if node.image else (None, None)
    if node.type in ("SEPARATE_COLOR", "SEPARATE_RGB") and ch is None:
        ch = CHANNEL_INDEX.get(link.from_socket.name.lower())
    if node.type == "GROUP" and node.node_tree:
        outs = [n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"]
        if outs:
            try:
                idx = list(node.outputs).index(link.from_socket)
                return find_image_ch(outs[0].inputs[idx], depth + 1, ch)
            except (ValueError, IndexError):
                return None, None
        return None, None
    for skip in (True, False):
        for inp in node.inputs:
            if skip and inp.name in SKIP_INPUTS:
                continue
            if inp.is_linked:
                r = find_image_ch(inp, depth + 1, ch)
                if r[0]:
                    return r
    return None, None


def find_image(sock, depth=0):
    return find_image_ch(sock, depth)[0]


def save_channel(img, ch, outdir, used):
    """Write one channel of an image as a grey PNG (used for packed ARM / ORM maps). None on failure."""
    try:
        import numpy as np
        w, h = img.size
        n = img.channels
        if ch >= n:
            return None
        px = np.empty(w * h * n, dtype=np.float32)
        img.pixels.foreach_get(px)
        data = px.reshape(h, w, n)[:, :, ch]
        out_px = np.ones((h, w, 4), dtype=np.float32)
        out_px[:, :, 0] = data
        out_px[:, :, 1] = data
        out_px[:, :, 2] = data
        base = safe(os.path.splitext(img.name)[0]) + "_" + "rgb"[ch]
        name, i = base, 1
        while name in used:
            i += 1
            name = "%s_%d" % (base, i)
        used.add(name)
        dest = os.path.join(outdir, name + ".png")
        new = bpy.data.images.new(name, w, h, alpha=False)
        new.colorspace_settings.name = "Non-Color"
        new.pixels.foreach_set(out_px.ravel())
        new.filepath_raw = dest
        new.file_format = "PNG"
        new.save()
        return os.path.basename(dest)
    except Exception:
        return None


def find_node(sock, ntype, depth=0):
    if depth > 14 or not sock.is_linked:
        return None
    node = sock.links[0].from_node
    if node.type == ntype:
        return node
    for inp in node.inputs:
        if inp.is_linked:
            r = find_node(inp, ntype, depth + 1)
            if r:
                return r
    return None


def save_image(img, outdir, used):
    base = safe(os.path.splitext(img.name)[0])
    fmt = img.file_format if img.file_format in EXT else "PNG"
    ext = EXT[fmt]
    n, i = base, 1
    while n in used:
        i += 1
        n = "%s_%d" % (base, i)
    used.add(n)
    dest = os.path.join(outdir, n + ext)
    src = bpy.path.abspath(img.filepath) if img.filepath else ""
    if img.source == "FILE" and not img.packed_file and src and os.path.isfile(src) \
            and os.path.splitext(src)[1].lower() == ext:
        shutil.copy2(src, dest)
    else:
        img.filepath_raw = dest
        img.file_format = fmt
        img.save()
    return os.path.basename(dest)


def socket_val(sock):
    try:
        v = sock.default_value
        return [float(x) for x in v] if hasattr(v, "__len__") else float(v)
    except Exception:
        return None


def extract_manifest(mat, outdir):
    """Write outdir/manifest.json (+ outdir/textures). Returns the manifest dict."""
    texdir = os.path.join(outdir, "textures")
    os.makedirs(texdir, exist_ok=True)
    used = set()
    warnings = []
    nt = mat.node_tree
    man = {"material_name": mat.name, "channels": {}, "values": {}, "uv_scale": [1.0, 1.0],
           "procedural": True, "warnings": warnings}
    if nt is None:
        warnings.append("material has no node tree")
        _write(outdir, man)
        return man
    output = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)), None)
    bsdf = find_node(output.inputs["Surface"], "BSDF_PRINCIPLED") if output else None
    if bsdf is None:
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        warnings.append("no Principled BSDF found")
        _write(outdir, man)
        return man

    channels, values, nodes = {}, {}, {}

    def chan(key, sock):
        if sock is None:
            return
        node, ch = find_image_ch(sock)
        if node:
            fname = None
            if ch is not None:                       # packed map: export just that channel
                fname = save_channel(node.image, ch, texdir, used)
                if fname is None:
                    warnings.append("%s: packed channel could not be split" % key)
            if fname is None:
                fname = save_image(node.image, texdir, used)
            channels[key] = {"file": fname, "colorspace": node.image.colorspace_settings.name}
            nodes[key] = node
        else:
            v = socket_val(sock)
            if v is not None:
                values[key] = v

    def get(*names):
        for n in names:
            if n in bsdf.inputs:
                return bsdf.inputs[n]
        return None

    chan("color", get("Base Color"))
    chan("roughness", get("Roughness"))
    chan("metallic", get("Metallic"))
    chan("alpha", get("Alpha"))
    chan("emission", get("Emission Color", "Emission"))
    chan("transmission", get("Transmission Weight", "Transmission"))
    for key, names in (("ior", ("IOR",)), ("emission_strength", ("Emission Strength",))):
        s = get(*names)
        if s is not None and not s.is_linked:
            v = socket_val(s)
            if v is not None:
                values[key] = v
    nsock = get("Normal")
    if nsock is not None and nsock.is_linked:
        has_nmap = find_node(nsock, "NORMAL_MAP") is not None
        chan("normal" if has_nmap else "bump", nsock)
    if output is not None and "Displacement" in output.inputs:
        chan("displacement", output.inputs["Displacement"])

    ref = nodes.get("color") or (next(iter(nodes.values())) if nodes else None)
    if ref is not None and "Vector" in ref.inputs and ref.inputs["Vector"].is_linked:
        m = find_node(ref.inputs["Vector"], "MAPPING")
        if m and "Scale" in m.inputs:
            sc = socket_val(m.inputs["Scale"])
            if sc:
                man["uv_scale"] = [sc[0], sc[1]]
    man["channels"], man["values"] = channels, values
    man["procedural"] = len(channels) == 0
    _write(outdir, man)
    return man


def _write(outdir, man):
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
