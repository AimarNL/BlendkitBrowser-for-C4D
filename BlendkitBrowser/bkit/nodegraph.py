# -*- coding: utf-8 -*-
"""Helpers around the maxon node-graph API (Arnold / Redshift node materials)."""
import maxon

from . import log as _log


def collect(graph):
    out = []

    def cb(n):
        out.append(n)
        return True
    graph.GetRoot().GetInnerNodes(maxon.NODE_KIND.NODE, False, cb)
    return out


def asset_id(n):
    try:
        return str(n.GetValue("net.maxon.node.attribute.assetid")[0])
    except Exception:
        try:
            return str(n.GetId())
        except Exception:
            return ""


def ports(node, io):
    try:
        root = node.GetInputs() if io == "in" else node.GetOutputs()
        return [(str(p.GetId()), p) for p in root.GetChildren()]
    except Exception as e:  # noqa
        _log.log("ports() failed: %r" % (e,))
        return []


def find_port(node, io, needles):
    ps = ports(node, io)
    for nd in needles:
        nd = nd.lower()
        for pid, p in ps:
            low = pid.lower()
            if low == nd or low.endswith("." + nd) or low.endswith("/" + nd):
                return p
    for nd in needles:
        nd = nd.lower()
        for pid, p in ps:
            if nd in pid.lower():
                return p
    return None


def child_port(port, needle):
    try:
        for c in port.GetChildren():
            if needle in str(c.GetId()).lower():
                return c
    except Exception:
        pass
    return None


def add_node(graph, candidates):
    last = None
    for cid in candidates:
        try:
            return graph.AddChild(maxon.Id(), maxon.Id(cid), maxon.DataDictionary()), cid
        except Exception as e:  # noqa
            last = e
    _log.log("could not create any of %s (%r)" % (candidates, last))
    return None, None


def set_value(port, *values):
    """Try several value representations until one is accepted."""
    for v in values:
        try:
            port.SetPortValue(v)
            return True
        except Exception:
            continue
    return False


def connect(src, dst):
    try:
        src.Connect(dst)
        return True
    except Exception as e:  # noqa
        _log.log("connect failed: %r" % (e,))
        return False


def dump_graph(graph, path, title=""):
    try:
        lines = ["== %s ==" % title]
        for n in collect(graph):
            lines.append("NODE %s" % asset_id(n))
            for io in ("in", "out"):
                for pid, p in ports(n, io):
                    lines.append("   %s %s" % (io.upper(), pid))
                    try:
                        for c in p.GetChildren():
                            lines.append("       .. %s" % str(c.GetId()))
                    except Exception:
                        pass
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    except Exception as e:  # noqa
        _log.log("dump_graph failed: %r" % (e,))


_asset_cache = None


def node_asset_ids(dump_path=None):
    """Ids of all node templates known to the asset system (best effort)."""
    global _asset_cache
    if _asset_cache is not None:
        return _asset_cache
    ids = []
    try:
        types = []
        for nm in ("NodeTemplate", "NodeTemplates"):
            t = getattr(maxon.AssetTypes, nm, None)
            if t is not None:
                types.append(t())
        repos = []
        for getter in ("GetUserPrefsRepository", "GetBuiltinRepository", "GetRepositoryDatabases"):
            g = getattr(maxon.AssetInterface, getter, None)
            if g is not None:
                try:
                    repos.append(g())
                except Exception:
                    pass
        for repo in repos:
            for ty in types:
                try:
                    for a in repo.FindAssets(ty, maxon.Id(), maxon.Id(), maxon.ASSET_FIND_MODE.LATEST):
                        ids.append(str(a.GetId()))
                except Exception as e:  # noqa
                    _log.log("FindAssets failed: %r" % (e,))
    except Exception as e:  # noqa
        _log.log("node asset discovery failed: %r" % (e,))
    _asset_cache = sorted(set(ids))
    _log.log("node asset discovery: %d ids" % len(_asset_cache))
    if dump_path and _asset_cache:
        try:
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write("\n".join(i for i in _asset_cache if any(k in i.lower() for k in ("arnold", "redshift"))))
        except OSError:
            pass
    return _asset_cache


def discover(token, suffixes, dump_path=None):
    suffixes = tuple(s.lower() for s in suffixes)
    found = [i for i in node_asset_ids(dump_path) if token in i.lower() and i.lower().endswith(suffixes)]
    return sorted(found, key=len)
