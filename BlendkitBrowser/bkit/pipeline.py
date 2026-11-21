# -*- coding: utf-8 -*-
"""Download -> (Blender) convert -> result.json. Pure Python, no c4d import (runs in worker threads)."""
import json
import os
import re
import shutil

from . import blender_bridge as bb
from . import log as _log
from .api import Asset

SCHEMA = 2


class PipelineError(Exception):
    pass


def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s or "x")).strip("_")[:n] or "x"


def cache_root(s):
    d = s.get("cache_dir") or os.path.join(s.dir, "cache")
    os.makedirs(d, exist_ok=True)
    return d


def asset_dir(s, asset):
    return os.path.join(cache_root(s), safe(asset.type or "misc"), safe(asset.key))


def res_dir(s, asset, res):
    return os.path.join(asset_dir(s, asset), safe(res))


def thumb_base(s, asset):
    return os.path.join(cache_root(s), "_thumbs", safe(asset.key))


def find_thumb(s, asset):
    base = thumb_base(s, asset)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if os.path.isfile(base + ext):
            return base + ext
    return None


def _valid(result):
    if not isinstance(result, dict) or result.get("schema") != SCHEMA:
        return False
    kind = result.get("kind")
    if kind in ("hdri", "model"):
        return os.path.isfile(result.get("path", ""))
    if kind == "material":
        return os.path.isfile(os.path.join(result.get("dir", ""), "manifest.json"))
    return False


def load_result(rdir):
    try:
        with open(os.path.join(rdir, "result.json"), "r", encoding="utf-8") as f:
            r = json.load(f)
        return r if _valid(r) else None
    except (OSError, ValueError):
        return None


def ready_resolutions(s, asset):
    base = asset_dir(s, asset)
    out = []
    if os.path.isdir(base):
        for d in sorted(os.listdir(base)):
            p = os.path.join(base, d)
            if os.path.isdir(p) and load_result(p):
                out.append(d)
    return out


def save_meta(s, asset):
    d = asset_dir(s, asset)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"raw": asset.raw}, f)


def list_local(s, asset_type):
    base = os.path.join(cache_root(s), safe(asset_type))
    out = []
    if not os.path.isdir(base):
        return out
    for d in sorted(os.listdir(base)):
        mp = os.path.join(base, d, "meta.json")
        try:
            with open(mp, "r", encoding="utf-8") as f:
                raw = json.load(f).get("raw")
            a = Asset(raw)
            if ready_resolutions(s, a):
                out.append(a)
        except (OSError, ValueError, AttributeError):
            continue
    return out


def delete_version(s, asset, res):
    shutil.rmtree(res_dir(s, asset, res), ignore_errors=True)
    if not ready_resolutions(s, asset):
        shutil.rmtree(asset_dir(s, asset), ignore_errors=True)


def sniff_ext(path):
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"BLENDER") or head[:2] == b"\x1f\x8b" or head[:4] == b"\x28\xb5\x2f\xfd":
        return ".blend"
    if head[:4] == b"\x76\x2f\x31\x01":
        return ".exr"
    if head.startswith(b"#?RADIANCE") or head.startswith(b"#?RGBE"):
        return ".hdr"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    return ".bin"


def prepare(s, client, asset, res_label, progress):
    """Make sure the asset/resolution is downloaded and converted. Returns result dict."""
    rdir = res_dir(s, asset, res_label)
    cached = load_result(rdir)
    if cached:
        return cached
    os.makedirs(rdir, exist_ok=True)
    f = asset.file_for(res_label)
    if not f:
        raise PipelineError("This asset has no '%s' file." % res_label)

    src = None
    for name in os.listdir(rdir):
        if name.startswith("source."):
            src = os.path.join(rdir, name)
    if not src:
        progress("Requesting link...", 0.0)
        url = client.get_download_url(f)
        tmp = os.path.join(rdir, "source.download")

        def dl(done, total):
            if total:
                progress("Downloading %.1f / %.1f MB" % (done / 1048576.0, total / 1048576.0), done / float(total))
            else:
                progress("Downloading %.1f MB" % (done / 1048576.0), 0.0)
        client.download_file(url, tmp, dl)
        src = os.path.join(rdir, "source" + sniff_ext(tmp))
        os.replace(tmp, src)
    ext = os.path.splitext(src)[1].lower()
    save_meta(s, asset)
    out_dir = os.path.join(rdir, "converted")
    os.makedirs(out_dir, exist_ok=True)
    name = safe(asset.name)

    if asset.type == "hdr":
        if ext in (".exr", ".hdr"):
            result = {"kind": "hdri", "path": src}
        elif ext == ".blend":
            progress("Extracting HDRI with Blender...", 0.0)
            dest = os.path.join(out_dir, name + ".exr")
            r = bb.run(bb.require_blender(s), src, "extract_hdri.py", ["--out", dest])
            result = {"kind": "hdri", "path": r["path"]}
        elif ext in (".png", ".jpg", ".tif"):
            result = {"kind": "hdri", "path": src}
        else:
            raise PipelineError("Unknown HDRI file type (%s)." % ext)
    elif asset.type == "material":
        if ext != ".blend":
            raise PipelineError("Unexpected material file type (%s)." % ext)
        progress("Extracting textures with Blender...", 0.0)
        r = bb.run(bb.require_blender(s), src, "extract_material.py",
                   ["--out", out_dir, "--name", asset.name])
        if r.get("procedural"):
            raise PipelineError("This material is procedural (no image textures). "
                                "Procedural materials are not supported yet.")
        result = {"kind": "material", "dir": out_dir, "warnings": r.get("warnings", [])}
    elif asset.type in ("model", "scene"):
        if ext != ".blend":
            raise PipelineError("Unexpected %s file type (%s)." % (asset.type, ext))
        fmt = s.get("model_format") or "fbx"
        is_scene = asset.type == "scene"
        progress("Converting %s with Blender (%s)..." % (asset.type, fmt.upper()), 0.0)
        r = bb.run(bb.require_blender(s), src, "convert_model.py",
                   ["--out", out_dir, "--name", name, "--format", fmt, "--scene", "1" if is_scene else "0"])
        result = {"kind": "model", "path": r["path"], "format": fmt, "warnings": r.get("warnings", []),
                  "materials_index": r.get("materials_index", ""), "is_scene": is_scene}
    else:
        raise PipelineError("Unsupported asset type '%s'." % asset.type)

    result["schema"] = SCHEMA
    result["asset_name"] = asset.name
    with open(os.path.join(rdir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    _log.log("Prepared %s (%s): %s" % (asset.name, res_label, result.get("kind")))
    progress("Ready", 1.0)
    return result
