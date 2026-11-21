# -*- coding: utf-8 -*-
"""Debug helper: dump the selected object's parameters / selected material's node graphs to a text file."""
import os

import c4d


def _dtype_name(dt):
    for n in ("DTYPE_LONG", "DTYPE_REAL", "DTYPE_BOOL", "DTYPE_STRING", "DTYPE_FILENAME", "DTYPE_BASELISTLINK",
              "DTYPE_COLOR", "DTYPE_VECTOR", "DTYPE_GROUP", "DTYPE_SEPARATOR", "DTYPE_BUTTON"):
        if getattr(c4d, n, None) == dt:
            return n[6:]
    return str(dt)


def _dump_params(obj, lines):
    try:
        for bc, pid, gid in obj.GetDescription(c4d.DESCFLAGS_DESC_0):
            try:
                name = bc[c4d.DESC_NAME]
                dt = pid[0].dtype
                row = "  id=%s dtype=%s name=%r" % (pid[0].id, _dtype_name(dt), name)
                if dt == c4d.DTYPE_LONG:
                    cyc = bc[c4d.DESC_CYCLE]
                    if cyc:
                        row += " cycle=%s" % [(i, str(l)) for i, l in cyc][:12]
                lines.append(row)
            except Exception:
                continue
    except Exception as e:  # noqa
        lines.append("  (description failed: %r)" % (e,))


def probe(doc, out_dir):
    lines = []
    obj = doc.GetActiveObject()
    if obj:
        lines.append("OBJECT name=%r type=%s plugin-id=%s" % (obj.GetName(), obj.GetType(), obj.GetType()))
        _dump_params(obj, lines)
    mat = doc.GetActiveMaterial()
    if mat:
        lines.append("MATERIAL name=%r type=%s" % (mat.GetName(), mat.GetType()))
        try:
            import maxon
            from . import nodegraph as ng
            nm = mat.GetNodeMaterialReference()
            for space in ("com.autodesk.arnold.nodespace", "com.redshift3d.redshift4c4d.class.nodespace",
                          "net.maxon.nodespace.standard"):
                try:
                    g = nm.GetGraph(maxon.Id(space))
                    if g is not None and not g.IsNullValue():
                        tmp = os.path.join(out_dir, "probe_graph.txt")
                        ng.dump_graph(g, tmp, "graph " + space)
                        lines.append("graph dumped for %s -> probe_graph.txt" % space)
                except Exception as e:  # noqa
                    lines.append("graph %s: %r" % (space, e))
        except Exception as e:  # noqa
            lines.append("node material probe failed: %r" % (e,))
        _dump_params(mat, lines)
    plugs = []
    try:
        for p in c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_OBJECT, True):
            n = p.GetName() or ""
            if any(k in n.lower() for k in ("arnold", "redshift", "rs ", "octane", "corona", "v-ray", "vray")):
                plugs.append("%s=%s" % (p.GetID(), n))
    except Exception:
        pass
    lines.append("RENDERER OBJECT PLUGINS: " + "; ".join(plugs))
    if not obj and not mat:
        lines.insert(0, "Nothing selected: select an object (e.g. an Arnold Sky / RS Dome) or click a material first.")
    path = os.path.join(out_dir, "probe.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
