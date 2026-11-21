# -*- coding: utf-8 -*-
"""Blendkit browser dialog. Layout, drawing and behaviour mirror the Poly Haven HDRI Browser plugin."""
import json
import os
import time
import webbrowser

import c4d
from c4d import gui

from . import api, filedrag, hdri_build, importer, licensenotice, linkmenu, pipeline, probe
from . import log as _log
from .draw import (SB_W, CELL_W, V, ScrollArea, fill_round, fill_round_ring, draw_dot, rounded_copy,
                   cut_corners, fmt_bytes, describe_file,
                   C_MAIN, C_SIDE, C_CARD, C_BADGE, C_CHIP, C_PURPLE, C_PURPLE_D, C_TEXT, C_DIM, C_WHITE)

SIDE_W = 228
SIDE_CW = SIDE_W - SB_W - 6
ROW_H = 32

# ---- gadget ids
(ID_ACCOUNT, ID_BTN_LOGIN, ID_BTN_SETTINGS, ID_OPENSITE) = range(1001, 1005)
ID_TYPE, ID_TYPE_HDR, ID_TYPE_MAT, ID_TYPE_MODEL, ID_TYPE_SCENE = 1010, 1011, 1012, 1013, 1014
(ID_SORT, ID_SEARCH, ID_RESULTS, ID_ZOOM) = range(1020, 1024)
ID_SIDE, ID_GRID = 1030, 1031
(ID_RES, ID_TARGET, ID_FOLDER, ID_BROWSE, ID_RETRY) = range(1040, 1045)
(ID_SELECTED, ID_DOWNLOAD, ID_INFO, ID_DISK, ID_DELETE, ID_STATUS) = range(1050, 1056)
ID_PRICE = 1060
PRICE_LIST = [("all", "All"), ("free", "Free"), ("pro", "PRO")]

TYPES = {ID_TYPE_HDR: "hdr", ID_TYPE_MAT: "material", ID_TYPE_MODEL: "model", ID_TYPE_SCENE: "scene"}
TYPE_IDS = {v: k for k, v in TYPES.items()}
TYPE_LABEL = {"hdr": "HDRIs", "material": "Materials", "model": "Models", "scene": "Scenes"}
DOWNLOADS = "__downloads__"
SORT_LIST = [label for label, _ in api.ORDERS] + ["My downloads"]
ENGINES = [("arnold", "Arnold"), ("redshift", "Redshift"), ("octane", "Octane"), ("corona", "Corona"),
           ("vray", "V-Ray"), ("c4d", "C4D Standard")]


# ================================================================= dialogs
class LoginDialog(gui.GeDialog):
    ID_KEY, ID_OPEN, ID_OK, ID_CANCEL, ID_HELP = 2001, 2002, 2003, 2004, 2005

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.key = None

    def CreateLayout(self):
        self.SetTitle("Blendkit login")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "", 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.AddStaticText(self.ID_HELP, c4d.BFH_SCALEFIT, 420, 60,
                           "1. Click 'Open profile page' and log in on the website.\n"
                           "2. Copy your API key from your profile.\n"
                           "3. Paste it below and press Save.", c4d.BORDER_NONE)
        self.AddButton(self.ID_OPEN, c4d.BFH_LEFT, 160, 0, "Open profile page")
        self.AddEditText(self.ID_KEY, c4d.BFH_SCALEFIT, 400, 0)
        self.GroupBegin(0, c4d.BFH_RIGHT, 0, 1, "", 0)
        self.AddButton(self.ID_OK, c4d.BFH_RIGHT, 90, 0, "Save")
        self.AddButton(self.ID_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.GroupEnd()
        self.GroupEnd()
        return True

    def Command(self, cid, msg):
        if cid == self.ID_OPEN:
            webbrowser.open(self.base.rstrip("/") + "/profile/")
        elif cid == self.ID_OK:
            self.key = self.GetString(self.ID_KEY).strip()
            self.Close()
        elif cid == self.ID_CANCEL:
            self.Close()
        return True


class SettingsDialog(gui.GeDialog):
    ID_BASE, ID_BLENDER, ID_BLENDER_B, ID_CACHE, ID_CACHE_B = 3001, 3002, 3003, 3004, 3005
    ID_APPLY, ID_DIAG, ID_LOG, ID_OK, ID_CANCEL, ID_FMT, ID_PROBE = 3007, 3008, 3009, 3010, 3011, 3012, 3013

    def __init__(self, settings, client):
        super().__init__()
        self.s = settings
        self.client = client

    def CreateLayout(self):
        self.SetTitle("Blendkit settings")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "", 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.AddStaticText(0, c4d.BFH_LEFT, 110, 0, "Site / API URL", c4d.BORDER_NONE)
        self.AddEditText(self.ID_BASE, c4d.BFH_SCALEFIT, 330, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "", c4d.BORDER_NONE)
        self.AddStaticText(0, c4d.BFH_LEFT, 110, 0, "Blender path", c4d.BORDER_NONE)
        self.AddEditText(self.ID_BLENDER, c4d.BFH_SCALEFIT, 330, 0)
        self.AddButton(self.ID_BLENDER_B, c4d.BFH_RIGHT, 70, 0, "Browse")
        self.AddStaticText(0, c4d.BFH_LEFT, 110, 0, "Save assets to", c4d.BORDER_NONE)
        self.AddEditText(self.ID_CACHE, c4d.BFH_SCALEFIT, 330, 0)
        self.AddButton(self.ID_CACHE_B, c4d.BFH_RIGHT, 70, 0, "Browse")
        self.AddStaticText(0, c4d.BFH_LEFT, 110, 0, "Model format", c4d.BORDER_NONE)
        self.AddComboBox(self.ID_FMT, c4d.BFH_LEFT, 160)
        self.AddChild(self.ID_FMT, 0, "FBX")
        self.AddChild(self.ID_FMT, 1, "glTF (GLB)")
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "", c4d.BORDER_NONE)
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "", 0)
        self.GroupBorderSpace(10, 0, 10, 10)
        self.AddCheckbox(self.ID_APPLY, c4d.BFH_LEFT, 0, 0, "Apply new materials to selected objects")
        self.GroupBegin(0, c4d.BFH_LEFT, 0, 1, "", 0)
        self.AddButton(self.ID_DIAG, c4d.BFH_LEFT, 0, 0, "Diagnostics (dump API responses)")
        self.AddButton(self.ID_LOG, c4d.BFH_LEFT, 0, 0, "Open log folder")
        self.AddButton(self.ID_PROBE, c4d.BFH_LEFT, 0, 0, "Probe selected object/material")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_RIGHT, 0, 1, "", 0)
        self.AddButton(self.ID_OK, c4d.BFH_RIGHT, 90, 0, "Save")
        self.AddButton(self.ID_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.GroupEnd()
        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetString(self.ID_BASE, self.s.get("api_base") or "")
        self.SetString(self.ID_BLENDER, self.s.get("blender_path") or "")
        self.SetString(self.ID_CACHE, self.s.get("cache_dir") or os.path.join(self.s.dir, "cache"))
        self.SetBool(self.ID_APPLY, bool(self.s.get("apply_to_selection")))
        self.SetInt32(self.ID_FMT, 1 if self.s.get("model_format") == "glb" else 0)
        return True

    def Command(self, cid, msg):
        if cid == self.ID_BLENDER_B:
            p = c4d.storage.LoadDialog(c4d.FILESELECTTYPE_ANYTHING, "Select blender executable")
            if p:
                self.SetString(self.ID_BLENDER, p)
        elif cid == self.ID_CACHE_B:
            p = c4d.storage.LoadDialog(c4d.FILESELECTTYPE_ANYTHING, "Select folder", c4d.FILESELECT_DIRECTORY)
            if p:
                self.SetString(self.ID_CACHE, p)
        elif cid == self.ID_DIAG:
            self.Apply()
            d = os.path.join(self.s.dir, "diagnostics")
            lines = self.client.dump_diagnostics(d)
            gui.MessageDialog("Saved to:\n%s\n\n%s" % (d, "\n".join(lines)))
            c4d.storage.ShowInFinder(d, True)
        elif cid == self.ID_LOG:
            c4d.storage.ShowInFinder(self.s.dir, True)
        elif cid == self.ID_PROBE:
            try:
                path = probe.probe(c4d.documents.GetActiveDocument(), self.s.dir)
                gui.MessageDialog("Probe written to:\n%s" % path)
                c4d.storage.ShowInFinder(path, True)
            except Exception as e:  # noqa
                gui.MessageDialog("Probe failed: %s" % e)
        elif cid == self.ID_OK:
            self.Apply()
            self.Close()
        elif cid == self.ID_CANCEL:
            self.Close()
        return True

    def Apply(self):
        self.s.set("api_base", self.GetString(self.ID_BASE).strip(), False)
        self.s.set("blender_path", self.GetString(self.ID_BLENDER).strip(), False)
        self.s.set("cache_dir", self.GetString(self.ID_CACHE).strip(), False)
        self.s.set("apply_to_selection", bool(self.GetBool(self.ID_APPLY)), False)
        self.s.set("model_format", "glb" if self.GetInt32(self.ID_FMT) == 1 else "fbx", False)
        self.s.save()



class Item:
    def __init__(self, asset):
        self.asset = asset
        self.key = asset.key
        self.bmp = None
        self.ready = False


def _dir_size(path):
    total = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def describe_result(res):
    try:
        if res.get("kind") == "material":
            return fmt_bytes(_dir_size(res["dir"]))
        return describe_file(res["path"])
    except Exception:
        return "?"


# ================================================================== sidebar
class Sidebar(ScrollArea):
    """Left sidebar: categories with count badges + filter chips (same drawing as the Poly Haven plugin)."""

    def GetMinSize(self):
        return SIDE_W, 120

    def build(self):
        h = self.host
        items, y = [], 6
        for row in h.sidebar_rows():
            if row["depth"] == 0:
                items.append(dict(k="cat", row=row, x=0, y=y, w=SIDE_CW, h=ROW_H - 2))
                y += ROW_H
            else:
                items.append(dict(k="child", row=row, x=16 * row["depth"], y=y,
                                  w=SIDE_CW - 16 * row["depth"], h=ROW_H - 6))
                y += ROW_H - 4
        y += 10
        return items, y

    def content_height(self):
        return self.build()[1]

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.begin_draw(x1, y1, x2, y2)
        h = self.host
        self.DrawSetPen(C_SIDE)
        self.DrawRectangle(x1, y1, x2, y2)
        items, total = self.build()
        self.clamp()
        H = self.area_h()
        fh = self.DrawGetFontHeight()
        for it in items:
            y = it["y"] - self.scroll
            if y + it["h"] < 0 or y > H:
                continue
            kind = it["k"]
            if kind == "cat":
                row = it["row"]
                sel = (row["slug"] == h.category)
                if sel:
                    fill_round(self, it["x"], y, it["x"] + it["w"], y + it["h"], 9, C_PURPLE, C_SIDE)
                bg = C_PURPLE if sel else C_SIDE
                self.DrawSetTextCol(C_WHITE if sel else C_TEXT, bg)
                ty = y + (it["h"] - fh) // 2
                if row["children"]:
                    self.DrawText("v" if row["expanded"] else ">", 8, ty)
                self.DrawText(row["label"][:24], 26, ty)
                if row["count"] is not None:
                    cs = str(row["count"])
                    bw = self.DrawGetTextWidth(cs) + 12
                    bx2 = it["x"] + it["w"] - 6
                    bcol = V(0.80, 0.55, 1.0) if sel else C_BADGE
                    fill_round(self, bx2 - bw, y + 5, bx2, y + it["h"] - 5, 8, bcol, C_PURPLE if sel else C_SIDE)
                    self.DrawSetTextCol(C_WHITE if sel else C_TEXT, bcol)
                    self.DrawText(cs, bx2 - bw + 6, ty)
            elif kind == "child":
                row = it["row"]
                sel = (row["slug"] == h.category)
                bg = C_PURPLE_D if sel else C_SIDE
                if sel:
                    fill_round(self, it["x"], y, it["x"] + it["w"], y + it["h"], 7, bg, C_SIDE)
                self.DrawSetTextCol(C_WHITE if sel else C_DIM, bg)
                ty = y + (it["h"] - fh) // 2
                if row["children"]:
                    self.DrawText("v" if row["expanded"] else ">", it["x"] + 2, ty)
                self.DrawText(row["label"][:20], it["x"] + 14, ty)
                if row["count"] is not None:
                    cs = str(row["count"])
                    tw = self.DrawGetTextWidth(cs)
                    self.DrawText(cs, it["x"] + it["w"] - tw - 8, ty)
            elif kind == "head":
                self.DrawSetTextCol(C_DIM, C_SIDE)
                self.DrawText("Filters", SIDE_CW // 2 - 20, y)
            elif kind == "sub":
                self.DrawSetTextCol(C_DIM, C_SIDE)
                self.DrawText(it["label"], it["x"], y)
            elif kind == "chip":
                on = (h.price == it["key"])
                fill = C_PURPLE_D if on else C_CHIP
                fill_round_ring(self, it["x"], y, it["x"] + it["w"], y + it["h"], 9, 1,
                                C_PURPLE if on else V(0.30), fill, C_SIDE)
                self.DrawSetTextCol(C_WHITE if on else C_TEXT, fill)
                self.DrawText(it["label"], it["x"] + 8, y + (it["h"] - fh) // 2)
        self.draw_scrollbar()

    def InputEvent(self, msg):
        if msg.GetInt32(c4d.BFM_INPUT_DEVICE) != c4d.BFM_INPUT_MOUSE:
            return False
        ch = msg.GetInt32(c4d.BFM_INPUT_CHANNEL)
        if ch == c4d.BFM_INPUT_MOUSEWHEEL:
            val = msg.GetInt32(c4d.BFM_INPUT_VALUE)
            self.scroll += -60 if val > 0 else 60
            self.clamp()
            self.Redraw()
            return True
        if ch == c4d.BFM_INPUT_MOUSELEFT:
            g = self.Global2Local()
            mx = msg.GetInt32(c4d.BFM_INPUT_X) + g["x"]
            my = msg.GetInt32(c4d.BFM_INPUT_Y) + g["y"]
            if mx >= self.area_w() - SB_W:
                self.scrollbar_click(mx, my)
                return True
            items, _ = self.build()
            my += self.scroll
            for it in items:
                if it["k"] in ("cat", "child") and \
                        it["x"] <= mx <= it["x"] + it["w"] and it["y"] <= my <= it["y"] + it["h"]:
                    self.host.sidebar_click(it["row"], mx < it["x"] + 22 and it["row"]["children"])
                    break
            return True
        return False


# ================================================================ thumb grid
class ThumbGrid(ScrollArea):
    """Continuously scrolling grid of asset cards (drag a downloaded asset out of it)."""

    def GetMinSize(self):
        return 180, 120

    def layout(self):
        W = self.area_w()
        cols = max(1, (W - SB_W) // self.host.cell_w)
        cw = (W - SB_W) // cols
        ch = int(cw * 0.70)
        return cols, cw, ch

    def content_height(self):
        cols, cw, ch = self.layout()
        n = len(self.host.items)
        return ((n + cols - 1) // cols) * ch

    def after_scroll(self):
        self.host.on_grid_scroll()
        self.Redraw()

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.begin_draw(x1, y1, x2, y2)
        self.DrawSetPen(C_MAIN)
        self.DrawRectangle(x1, y1, x2, y2)
        h = self.host
        self.clamp()
        cols, cw, ch = self.layout()
        H = self.area_h()
        items = h.items
        if not items:
            self.DrawSetTextCol(C_DIM, C_MAIN)
            self.DrawText(h.empty_text(), 20, 20)
        first_row = int(self.scroll) // ch
        last_row = (int(self.scroll) + H) // ch
        fh = self.DrawGetFontHeight()
        for row in range(first_row, last_row + 1):
            for col in range(cols):
                idx = row * cols + col
                if idx >= len(items):
                    break
                it = items[idx]
                cx = col * cw
                cy = row * ch - int(self.scroll)
                sel = (idx == h.selected)
                if sel:
                    fill_round_ring(self, cx + 4, cy + 4, cx + cw - 5, cy + ch - 5, 11, 2, C_PURPLE, C_CARD, C_MAIN)
                else:
                    fill_round(self, cx + 6, cy + 6, cx + cw - 7, cy + ch - 7, 9, C_CARD, C_MAIN)
                bmp = it.bmp
                tw = cw - 20
                max_th = ch - 44
                if bmp is not None and bmp.GetBw() > 0:
                    th = max(1, int(tw * bmp.GetBh() / bmp.GetBw()))
                    if th > max_th:
                        tw = int(tw * max_th / th)
                        th = max_th
                    ox = cx + (cw - tw) // 2
                    rb = h.round_cache.get((it.key, tw, th))
                    if rb is None:
                        try:
                            rb = rounded_copy(bmp, tw, th, 9, C_CARD)
                        except Exception as e:  # noqa
                            _log.log("rounded thumbnail: %s" % e)
                            rb = False
                        if len(h.round_cache) > 200:
                            h.round_cache.clear()
                        h.round_cache[(it.key, tw, th)] = rb
                    if rb:
                        self.DrawBitmap(rb, ox, cy + 10, tw, th, 0, 0, tw, th, c4d.BMP_NORMALSCALED)
                    else:
                        self.DrawBitmap(bmp, ox, cy + 10, tw, th, 0, 0, bmp.GetBw(), bmp.GetBh(),
                                        c4d.BMP_NORMALSCALED)
                        cut_corners(self, ox, cy + 10, ox + tw - 1, cy + 10 + th - 1, 8, C_CARD)
                else:
                    self.DrawSetTextCol(C_DIM, C_CARD)
                    self.DrawText("loading...", cx + 16, cy + 50)
                self.DrawSetTextCol(C_WHITE if sel else C_TEXT, C_CARD)
                name = it.asset.name
                dd = 14
                free = not it.asset.is_pro()
                label = "FREE" if free else "PRO"
                bw = (self.DrawGetTextWidth(label) + 14) if label else 0
                room = max(8, (cw - dd - 44 - bw - (6 if bw else 0)) // 7)
                shown = name if len(name) <= room else name[:max(1, room - 2)] + ".."
                self.DrawText(shown, cx + 12, cy + ch - 28)
                dot_x = cx + cw - 14 - dd
                draw_dot(self, dot_x, cy + ch - 28 + (fh - dd) // 2, dd, it.ready, C_CARD)
                if label:
                    bcol = V(0.20, 0.52, 0.32) if free else V(0.88, 0.52, 0.14)
                    bx2 = dot_x - 8
                    by1 = cy + ch - 28 - 1
                    fill_round(self, bx2 - bw, by1, bx2, by1 + fh + 3, 7, bcol, C_CARD)
                    self.DrawSetTextCol(C_WHITE, bcol)
                    self.DrawText(label, bx2 - bw + 7, by1 + 1)
        self.draw_scrollbar()

    def InputEvent(self, msg):
        if msg.GetInt32(c4d.BFM_INPUT_DEVICE) != c4d.BFM_INPUT_MOUSE:
            return False
        chn = msg.GetInt32(c4d.BFM_INPUT_CHANNEL)
        if chn == c4d.BFM_INPUT_MOUSEWHEEL:
            cols, cw, ch = self.layout()
            val = msg.GetInt32(c4d.BFM_INPUT_VALUE)
            self.scroll += -(ch // 2) if val > 0 else (ch // 2)
            self.clamp()
            self.after_scroll()
            return True
        if chn == c4d.BFM_INPUT_MOUSERIGHT:
            g = self.Global2Local()
            mx = msg.GetInt32(c4d.BFM_INPUT_X) + g["x"]
            my = msg.GetInt32(c4d.BFM_INPUT_Y) + g["y"]
            if mx < self.area_w() - SB_W:
                cols, cw, ch = self.layout()
                idx = ((my + int(self.scroll)) // ch) * cols + mx // cw
                if 0 <= mx // cw < cols and 0 <= idx < len(self.host.items):
                    self.host.select(idx)
                    self.host.asset_menu(self, mx, my, self.host.items[idx])
            return True
        if chn == c4d.BFM_INPUT_MOUSELEFT:
            g = self.Global2Local()
            mx = msg.GetInt32(c4d.BFM_INPUT_X) + g["x"]
            my = msg.GetInt32(c4d.BFM_INPUT_Y) + g["y"]
            if mx >= self.area_w() - SB_W:
                self.scrollbar_click(mx, my)
                return True
            cols, cw, ch = self.layout()
            col = mx // cw
            row = (my + int(self.scroll)) // ch
            idx = row * cols + col
            if 0 <= col < cols and 0 <= idx < len(self.host.items):
                self.host.select(idx)
                if msg.GetInt32(c4d.BFM_INPUT_DOUBLECLICK):
                    self.host.start_download()
                else:
                    it = self.host.items[idx]
                    drag = self.host.drag_info(it)    # only downloaded assets can be dragged
                    if drag:
                        try:
                            if drag[2]:
                                self.host.prepare_drop(it)
                                if not filedrag.start_drag([drag[0]], _log.log):
                                    self.host.cancel_drop()
                                    self.HandleMouseDrag(msg, drag[1], drag[0], 0)
                                elif not filedrag.last_dragged:
                                    self.host.cancel_drop()      # plain click
                                else:
                                    self.host.finish_drop()
                            else:
                                self.HandleMouseDrag(msg, drag[1], drag[0], 0)
                        except Exception as e:  # noqa
                            self.host.cancel_drop()
                            _log.log("drag: %s" % e)
            return True
        return False


# ============================================================== main dialog
class BrowserDialog(gui.GeDialog):
    def __init__(self, settings, client, runner):
        super().__init__()
        self.s, self.client, self.runner = settings, client, runner
        self.asset_type = settings.get("last_type") or "hdr"
        self.items, self.selected = [], -1
        self.next_url, self.total, self.loading, self.gen = None, 0, False, 0
        self.category = None
        self.categories = {}
        self.expanded = set()
        self.price = "all"
        self.local_count = 0
        self.cell_w = int(settings.get("preview_size") or 250)
        self.round_cache = {}
        self.grid, self.side = ThumbGrid(self), Sidebar(self)
        self.busy, self.progress_text = set(), ""
        self.res_labels = []
        self.disk_list = []
        self._drop = None
        self._search_due = None
        self._thumb_pending = set()
        self.logged_in_label = ""
        self.last_error = ""
        self.status_text = ""
        self._auto_pages = 0
        self._scan = {"seen": 0, "free": 0, "pro": 0, "unk": 0, "logged": False, "kinds": {}}

    # ------------------------------------------------------------ layout (same arrangement as Poly Haven)
    def CreateLayout(self):
        self.SetTitle("Blendkit Browser")

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 0, 1)
        self.GroupBorderSpace(8, 6, 8, 0)
        self.AddStaticText(ID_ACCOUNT, c4d.BFH_SCALEFIT, 120, 0, "Not logged in")
        self.AddButton(ID_BTN_LOGIN, c4d.BFH_RIGHT, 90, 0, "Login")
        self.AddButton(ID_BTN_SETTINGS, c4d.BFH_RIGHT, 90, 0, "Settings")
        self.GroupEnd()

        # header row 1: type | sort | price
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 0, 1)
        self.GroupBorderSpace(8, 6, 8, 2)
        self.AddRadioGroup(ID_TYPE, c4d.BFH_LEFT, 4, 1)
        self.AddChild(ID_TYPE, ID_TYPE_HDR, "HDRIs")
        self.AddChild(ID_TYPE, ID_TYPE_MAT, "Materials")
        self.AddChild(ID_TYPE, ID_TYPE_MODEL, "Models")
        self.AddChild(ID_TYPE, ID_TYPE_SCENE, "Scenes")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Sort by:")
        self.AddComboBox(ID_SORT, c4d.BFH_LEFT, 110)
        for i, s in enumerate(SORT_LIST):
            self.AddChild(ID_SORT, i, s)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Price:")
        self.AddComboBox(ID_PRICE, c4d.BFH_LEFT, 70)
        for i, (_k, label) in enumerate(PRICE_LIST):
            self.AddChild(ID_PRICE, i, label)
        self.GroupEnd()

        # header row 2: search | results | preview | site
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 0, 1)
        self.GroupBorderSpace(8, 0, 8, 4)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Search:")
        self.AddEditText(ID_SEARCH, c4d.BFH_SCALEFIT, 80, 0)
        self.AddStaticText(ID_RESULTS, c4d.BFH_RIGHT, 80, 0, name="0 results")
        self.AddStaticText(0, c4d.BFH_LEFT, name="Preview size:")
        self.AddSlider(ID_ZOOM, c4d.BFH_LEFT, 90, 0)
        self.AddButton(ID_OPENSITE, c4d.BFH_RIGHT, name="Open blendkit.com")
        self.GroupEnd()

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 2, 0)
        self.GroupBorderSpace(4, 2, 4, 2)
        self.AddUserArea(ID_SIDE, c4d.BFH_LEFT | c4d.BFV_SCALEFIT, SIDE_W, 120)
        self.AttachUserArea(self.side, ID_SIDE)
        self.AddUserArea(ID_GRID, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 180, 120)
        self.AttachUserArea(self.grid, ID_GRID)
        self.GroupEnd()

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 5, 0)
        self.GroupBorderSpace(8, 2, 8, 2)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Resolution:")
        self.AddComboBox(ID_RES, c4d.BFH_LEFT, 130)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Save to:")
        self.AddEditText(ID_FOLDER, c4d.BFH_SCALEFIT, 100, 0)
        self.AddButton(ID_BROWSE, c4d.BFH_RIGHT, name="Browse...")
        self.GroupEnd()

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupBorderSpace(8, 2, 8, 2)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Render engine:")
        self.AddComboBox(ID_TARGET, c4d.BFH_LEFT, 150)
        for i, (_k, label) in enumerate(ENGINES):
            self.AddChild(ID_TARGET, i, label)
        self.GroupEnd()
        self.AddStaticText(0, c4d.BFH_SCALEFIT, name="   (double-click = download & build;  drag a downloaded asset into the viewport)")

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupBorderSpace(8, 2, 8, 2)
        self.AddStaticText(ID_SELECTED, c4d.BFH_SCALEFIT, name="Selected: -")
        self.AddButton(ID_DOWNLOAD, c4d.BFH_RIGHT, name="Download")
        self.AddButton(ID_RETRY, c4d.BFH_RIGHT, name="Reload list")
        self.GroupEnd()
        self.AddStaticText(ID_INFO, c4d.BFH_SCALEFIT, name="")

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupBorderSpace(8, 2, 8, 2)
        self.AddStaticText(0, c4d.BFH_LEFT, name="Downloaded versions:")
        self.AddComboBox(ID_DISK, c4d.BFH_SCALEFIT, 150)
        self.AddButton(ID_DELETE, c4d.BFH_RIGHT, name="Delete this file")
        self.GroupEnd()

        self.AddStaticText(ID_STATUS, c4d.BFH_SCALEFIT, name="")
        licensenotice.add_footer(self, "blendkit.com")
        return True

    def InitValues(self):
        self.SetInt32(ID_TYPE, TYPE_IDS[self.asset_type])
        self.SetInt32(ID_SORT, 0)
        self.SetInt32(ID_PRICE, 0)
        self.SetInt32(ID_ZOOM, self.cell_w, 150, 380, 10)
        self.SetString(ID_FOLDER, pipeline.cache_root(self.s))
        cur = self.s.get("renderer") or "arnold"
        self.SetInt32(ID_TARGET, next((i for i, (k, _) in enumerate(ENGINES) if k == cur), 0))
        self.refresh_local_count()
        self.refresh_disk()
        self.update_account()
        self.SetTimer(150)
        self.verify_key()
        self.load_categories()
        self.start_search()
        return True

    def DestroyWindow(self):
        self.SetTimer(0)

    # ------------------------------------------------------------ helpers
    def status(self, text):
        self.status_text = text
        self.SetString(ID_STATUS, text)

    def current_res(self):
        idx = self.GetInt32(ID_RES)
        return self.res_labels[idx] if 0 <= idx < len(self.res_labels) else None

    def asset_menu(self, area, mx, my, item):
        """Right-click on a card: small menu to open the asset's page on blendkit.com."""
        base = api.WEB_BASE
        try:
            url = item.asset.web_url(base)
        except Exception as e:  # noqa
            _log.log("asset page url: %s" % e)
            return
        linkmenu.show(area, mx, my, "blendkit.com", url, item.asset.name)

    def selected_item(self):
        return self.items[self.selected] if 0 <= self.selected < len(self.items) else None

    def empty_text(self):
        if self.loading:
            return "Loading..."
        return self.last_error or "No assets found."

    def refresh_local_count(self):
        try:
            self.local_count = len(pipeline.list_local(self.s, self.asset_type))
        except Exception:
            self.local_count = 0

    def update_account(self):
        if self.s.get("api_key"):
            self.SetString(ID_ACCOUNT, "Logged in" + (": " + self.logged_in_label if self.logged_in_label else ""))
            self.SetString(ID_BTN_LOGIN, "Logout")
        else:
            self.SetString(ID_ACCOUNT, "Not logged in (browsing works, downloads need your API key)")
            self.SetString(ID_BTN_LOGIN, "Login")

    # ------------------------------------------------------------ account
    def verify_key(self):
        if not self.s.get("api_key"):
            return

        def done(res, err):
            if err:
                self.logged_in_label = ""
                self.status("Login check failed: %s" % err)
            else:
                self.logged_in_label = res
            self.update_account()
        self.runner.submit(lambda: self.client.user_label(self.client.me()), done)

    def do_login(self):
        if self.s.get("api_key"):
            self.s.set("api_key", "")
            self.logged_in_label = ""
            self.update_account()
            self.status("Logged out.")
            return
        dlg = LoginDialog(api.WEB_BASE)
        dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=220)
        if dlg.key:
            self.s.set("api_key", dlg.key)
            self.status("Checking key...")
            self.update_account()
            self.verify_key()
            self.start_search()

    # ------------------------------------------------------------ categories / sidebar
    def load_categories(self):
        t = self.asset_type
        if t in self.categories:
            return

        def done(res, err):
            if err:
                _log.log("categories failed: %s" % err)
            else:
                self.categories[t] = res
            self.side.Redraw()
        self.runner.submit(lambda: self.client.categories(t), done)

    def sidebar_rows(self):
        cats = self.categories.get(self.asset_type) or []
        total = sum(c["count"] for c in cats) or None
        rows = [{"label": "All " + TYPE_LABEL[self.asset_type], "count": total, "slug": None,
                 "depth": 0, "children": False, "expanded": False},
                {"label": "My Downloads", "count": self.local_count, "slug": DOWNLOADS,
                 "depth": 0, "children": False, "expanded": False}]

        def add(c, depth):
            has = bool(c["children"])
            exp = c["slug"] in self.expanded
            rows.append({"label": c["name"], "count": c["count"], "slug": c["slug"],
                         "depth": depth, "children": has, "expanded": exp})
            if has and exp:
                for ch in c["children"]:
                    add(ch, depth + 1)
        for c in cats:
            add(c, 0)
        return rows

    def sidebar_click(self, row, on_arrow):
        if on_arrow:
            if row["slug"] in self.expanded:
                self.expanded.discard(row["slug"])
            else:
                self.expanded.add(row["slug"])
            self.side.Redraw()
            return
        self.set_category(row["slug"])

    def set_category(self, slug):
        self.category = slug
        self.SetInt32(ID_SORT, len(SORT_LIST) - 1 if slug == DOWNLOADS else
                      (0 if self.GetInt32(ID_SORT) == len(SORT_LIST) - 1 else self.GetInt32(ID_SORT)))
        self.side.Redraw()
        self.start_search()

    # ------------------------------------------------------------ search
    def start_search(self):
        self.gen += 1
        gen = self.gen
        self._auto_pages = 0
        self._scan = {"seen": 0, "free": 0, "pro": 0, "unk": 0, "logged": False, "kinds": {}}
        self.items, self.selected, self.next_url, self.total = [], -1, None, 0
        self.grid.scroll = 0
        self.last_error = ""
        self.select(-1)
        if self.category == DOWNLOADS:
            self.show_downloads()
            return
        self.loading = True
        self.SetString(ID_RESULTS, "")
        sort_idx = max(0, self.GetInt32(ID_SORT))
        order = api.ORDERS[min(sort_idx, len(api.ORDERS) - 1)][1]
        path = self.client.search_path(self.asset_type, self.GetString(ID_SEARCH).strip(),
                                       self.category, order, price="free" if self.price == "free" else None)
        self.status("Searching...")
        self.runner.submit(lambda: self.client.search(path), lambda r, e: self.search_done(gen, r, e))
        self.grid.Redraw()

    def search_done(self, gen, res, err):
        if gen != self.gen:
            return
        self.loading = False
        if err:
            self.last_error = "Search failed: %s" % err
            self.status(self.last_error)
            self.grid.Redraw()
            return
        assets, nxt, count = res
        self.next_url = nxt
        self.total = count or 0
        self.add_assets(self._price_filter(assets))
        if self.price == "pro":
            self.SetString(ID_RESULTS, "%d PRO loaded" % len(self.items))
        else:
            self.SetString(ID_RESULTS, "%s results" % (self.total or len(self.items)))
            self.status("")
        self._auto_more()

    def add_assets(self, assets):
        for a in assets:
            it = Item(a)
            it.ready = bool(pipeline.ready_resolutions(self.s, a))
            self.items.append(it)
            self.request_thumb(it)
        self.grid.Redraw()

    def can_load_more(self):
        return bool(self.next_url) and not self.loading and self.category != DOWNLOADS

    def on_grid_scroll(self):
        if self.grid.scroll >= self.grid.max_scroll() - 300:
            self.load_more()

    def load_more(self):
        if not self.can_load_more():
            return
        self.loading = True
        gen, url = self.gen, self.next_url
        self.next_url = None
        self.runner.submit(lambda: self.client.search(url), lambda r, e: self.more_done(gen, r, e))

    def more_done(self, gen, res, err):
        if gen != self.gen:
            return
        self.loading = False
        if err:
            self.status("Loading more failed: %s" % err)
            return
        assets, nxt, _ = res
        self.next_url = nxt
        self.add_assets(self._price_filter(assets))
        if self.price == "pro":
            self.SetString(ID_RESULTS, "%d PRO loaded" % len(self.items))
        self._auto_more()

    # PRO is filtered here: the API keyword for "not free" is not known to work, so we keep only
    # assets whose isFree is False and keep paging until the grid is reasonably filled.
    def _price_filter(self, assets):
        if self.price != "pro":
            return assets
        sc = self._scan
        sc["seen"] += len(assets)
        sc["free"] += sum(1 for a in assets if a.is_free is True)
        sc["unk"] += sum(1 for a in assets if a.is_free is None)
        if assets and not sc["logged"]:
            sc["logged"] = True
            a = assets[0]
            _log.log("asset keys: %s | isFree=%r canDownload=%r" % (sorted(a.raw.keys()), a.is_free, a.can_download))
        pro = [a for a in assets if a.is_pro()]
        sc["pro"] += len(pro)
        for a in assets:
            k = a.access_key()
            sc["kinds"][k] = sc["kinds"].get(k, 0) + 1
        return pro

    def _scan_text(self):
        sc = self._scan
        txt = "PRO scan: %d checked, %d PRO (free %d, unknown %d)" % (sc["seen"], sc["pro"], sc["free"], sc["unk"])
        if sc["pro"] == 0 and sc["kinds"]:
            top = sorted(sc["kinds"].items(), key=lambda kv: -kv[1])[:2]
            txt += "  [" + " ; ".join("%s x%d" % kv for kv in top) + "]"
        return txt

    def _auto_more(self):
        if self.price != "pro":
            return
        if len(self.items) < 24 and self.can_load_more() and self._auto_pages < 40:
            self._auto_pages += 1
            self.status(self._scan_text() + ", page %d..." % self._auto_pages)
            self.load_more()
        else:
            end = " - scroll down for more" if self.next_url else " - end of list (API count %s)" % (self.total or "?")
            self.status(self._scan_text() + end)
            _log.log(self._scan_text() + end)

    def show_downloads(self):
        self.refresh_local_count()
        kw = self.GetString(ID_SEARCH).strip().lower()
        assets = pipeline.list_local(self.s, self.asset_type)
        if kw:
            assets = [a for a in assets if kw in a.name.lower()]
        self.add_assets(assets)
        self.SetString(ID_RESULTS, "%d downloaded" % len(self.items))
        self.side.Redraw()

    # ------------------------------------------------------------ thumbnails
    def request_thumb(self, it):
        if it.bmp is not None:
            return
        existing = pipeline.find_thumb(self.s, it.asset)
        if existing:
            self.load_bitmap(it, existing)
            return
        if not it.asset.thumb_url or it.key in self._thumb_pending:
            return
        self._thumb_pending.add(it.key)
        base, url = pipeline.thumb_base(self.s, it.asset), it.asset.thumb_url

        def done(res, err):
            self._thumb_pending.discard(it.key)
            if res:
                self.load_bitmap(it, res)
                self.grid.Redraw()
        self.runner.submit(lambda: self.client.download_thumb(url, base), done)

    def load_bitmap(self, it, path):
        bmp = c4d.bitmaps.BaseBitmap()
        res = bmp.InitWith(path)
        if isinstance(res, tuple):
            res = res[0]
        if res == c4d.IMAGERESULT_OK:
            it.bmp = bmp
        else:
            _log.log("thumbnail not readable: %s" % path)

    # ------------------------------------------------------------ selection / info
    def select(self, idx):
        self.selected = idx
        self.grid.Redraw()
        self.relabel_res()
        self.refresh_disk()
        self.update_info()

    @staticmethod
    def _dims(label):
        try:
            w = int(round(float(label[:-1]) * 1024))
            return w, w // 2
        except Exception:
            return None

    @staticmethod
    def _file_size(f):
        for k in ("fileSize", "filesize", "size"):
            if f.get(k):
                return f[k]
        return None

    def relabel_res(self):
        it = self.selected_item()
        self.FreeChildren(ID_RES)
        self.res_labels = []
        if not it:
            self.AddChild(ID_RES, 0, "-")
            self.SetInt32(ID_RES, 0)
            self.Enable(ID_RES, False)
            return
        self.Enable(ID_RES, True)
        a = it.asset
        ready = pipeline.ready_resolutions(self.s, a)
        pref = self.s.get("resolution_pref")
        sel = 0
        for i, (lab, f) in enumerate(a.resolutions()):
            self.res_labels.append(lab)
            text = lab
            if a.type == "hdr":
                wh = self._dims(lab)
                if wh:
                    text += "   %d x %d" % wh
            sz = self._file_size(f)
            if sz:
                text += "   %s" % fmt_bytes(sz)
            if pipeline.safe(lab) in ready:
                text += "   [downloaded]"
            self.AddChild(ID_RES, i, text)
            if lab == pref:
                sel = i
        if not self.res_labels:
            self.AddChild(ID_RES, 0, "(no files)")
        self.SetInt32(ID_RES, sel)

    def update_info(self):
        it = self.selected_item()
        if not it:
            self.SetString(ID_SELECTED, "Selected: -")
            self.SetString(ID_INFO, "")
            return
        a = it.asset
        price = "free" if a.is_free else ("PRO (needs a plan)" if a.is_free is False else "")
        lock = "   -  LOCKED for your account" if a.is_locked() else ""
        self.SetString(ID_SELECTED, "Selected: %s   by %s   %s%s" % (a.name, a.author or "?", price, lock))
        parts = []
        res = self.current_res()
        if res:
            wh = self._dims(res) if a.type == "hdr" else None
            if wh:
                parts.append("%s: %d x %d px" % (res, wh[0], wh[1]))
            f = a.file_for(res)
            sz = self._file_size(f) if f else None
            if sz:
                parts.append("download size: %s" % fmt_bytes(sz))
        ready = pipeline.ready_resolutions(self.s, a)
        if ready:
            bits = []
            for r in ready:
                rr = pipeline.load_result(pipeline.res_dir(self.s, a, r))
                bits.append("%s (%s)" % (r, describe_result(rr) if rr else "?"))
            parts.append("on disk: " + "; ".join(bits))
        else:
            parts.append("not downloaded yet")
        self.SetString(ID_INFO, "   |   ".join(parts))

    def refresh_disk(self):
        it = self.selected_item()
        ready = pipeline.ready_resolutions(self.s, it.asset) if it else []
        self.disk_list = ready
        self.FreeChildren(ID_DISK)
        if not ready:
            self.AddChild(ID_DISK, 0, "(nothing downloaded for this asset)")
            self.SetInt32(ID_DISK, 0)
            self.Enable(ID_DISK, False)
            self.Enable(ID_DELETE, False)
            return
        self.Enable(ID_DISK, True)
        self.Enable(ID_DELETE, True)
        cur = pipeline.safe(self.current_res() or "")
        sel = 0
        for i, r in enumerate(ready):
            rr = pipeline.load_result(pipeline.res_dir(self.s, it.asset, r))
            self.AddChild(ID_DISK, i, "%s    %s" % (r, describe_result(rr) if rr else "?"))
            if r == cur:
                sel = i
        self.SetInt32(ID_DISK, sel)

    def choose_disk(self):
        i = self.GetInt32(ID_DISK)
        if 0 <= i < len(self.disk_list):
            for j, lab in enumerate(self.res_labels):
                if pipeline.safe(lab) == self.disk_list[i]:
                    self.SetInt32(ID_RES, j)
                    break
            self.update_info()

    def delete_selected_file(self):
        it = self.selected_item()
        i = self.GetInt32(ID_DISK)
        if not it or not (0 <= i < len(self.disk_list)):
            self.status("Nothing to delete.")
            return
        r = self.disk_list[i]
        if not gui.QuestionDialog("Delete the downloaded '%s' version of '%s'?\n\n"
                                  "Scenes that use it will lose the textures." % (r, it.asset.name)):
            return
        pipeline.delete_version(self.s, it.asset, r)
        self.refresh_local_count()
        it.ready = bool(pipeline.ready_resolutions(self.s, it.asset))
        if self.category == DOWNLOADS:
            self.start_search()
        else:
            self.relabel_res()
            self.refresh_disk()
            self.update_info()
            self.grid.Redraw()
        self.status("Deleted '%s' (%s)." % (it.asset.name, r))

    def picked_result(self, it):
        """result.json of the downloaded version used by the current resolution."""
        ready = pipeline.ready_resolutions(self.s, it.asset)
        if not ready:
            return None
        cur = pipeline.safe(self.current_res() or "") if self.selected_item() is it else ""
        use = cur if cur in ready else ready[0]
        return pipeline.load_result(pipeline.res_dir(self.s, it.asset, use))

    def drag_info(self, it):
        """(path, drag type, shell) of a downloaded asset, or None.

        ``shell`` is True for models: the downloaded file is dragged through the Windows
        shell so Cinema 4D gets a real file drop. HDRIs and textures keep the native drag.
        """
        r = self.picked_result(it)
        if not r:
            return None
        kind = r.get("kind")
        if kind == "hdri":
            return r["path"], c4d.DRAGTYPE_FILENAME_IMAGE, False
        if kind == "model":
            return r["path"], c4d.DRAGTYPE_FILENAME_OTHER, True
        if kind == "material":
            try:
                with open(os.path.join(r["dir"], "manifest.json"), "r", encoding="utf-8") as f:
                    man = json.load(f)
                c = man.get("channels", {}).get("color")
                if c:
                    return os.path.join(r["dir"], "textures", c["file"]), c4d.DRAGTYPE_FILENAME_IMAGE, False
            except Exception:
                pass
        return None

    def prepare_drop(self, it):
        """Snapshot the scene before a model is dragged in (materials are rebuilt after)."""
        r = self.picked_result(it)
        if not r:
            self._drop = None
            return
        doc = c4d.documents.GetActiveDocument()
        self._drop = {
            "doc": doc,
            "docid": importer.doc_id(doc),
            "before": importer.top_guids(doc),
            "mats": importer.mat_guids(doc),
            "result": r,
            "name": it.asset.name,
            "engine": self.s.get("renderer") or "arnold",
            "until": time.time() + 8.0,
        }

    def cancel_drop(self):
        self._drop = None

    def finish_drop(self):
        """After a shell drag: replace the dropped import with our own (materials included)."""
        job = self._drop
        if not job:
            return True
        doc = c4d.documents.GetActiveDocument()
        if not importer.same_doc(doc, job):
            self._drop = None            # another document is active now: never touch it
            return True
        before = job["before"]
        roots = importer.dropped_roots(doc, before)
        if not roots:
            if time.time() < job["until"]:
                return False             # Cinema 4D may still be importing; Timer retries
            self._drop = None
            return True
        # let Cinema 4D finish adding every dropped object before replacing them
        if job.get("seen") is None:
            job["seen"] = time.time()
            return False
        if time.time() - job["seen"] < 0.6:
            return False
        self._drop = None
        r = job["result"]
        dump = os.path.join(self.s.dir, "graph_dump.txt")
        msg = importer.finish_drop(doc, roots, job["name"], r.get("path", ""),
                                   r.get("materials_index", ""), job["engine"], dump,
                                   job["mats"], label="Scene" if r.get("is_scene") else "Model")
        self.refresh_local_count()
        self.grid.Redraw()
        self.status(msg)
        return True

    # ------------------------------------------------------------ download / build
    def start_download(self):
        it = self.selected_item()
        if not it:
            self.status("Select an asset first.")
            return
        a = it.asset
        res = self.current_res()
        if not res:
            gui.MessageDialog("This asset has no downloadable file.")
            return
        if a.is_locked():
            gui.MessageDialog("This asset is locked for your account (it needs a Blendkit plan).")
            return
        if not self.s.get("api_key") and not pipeline.load_result(pipeline.res_dir(self.s, a, res)):
            gui.MessageDialog("Please log in first (Login button). Downloads need your API key.")
            return
        key = (a.key, res)
        if key in self.busy:
            return
        self.busy.add(key)
        self.progress_text = "%s: starting..." % a.name

        def progress(text, frac):
            self.progress_text = "%s: %s" % (a.name, text)

        self.runner.submit(lambda: pipeline.prepare(self.s, self.client, a, res, progress),
                           lambda r, e: self.prepared(it, key, r, e))

    def prepared(self, it, key, result, err):
        self.busy.discard(key)
        if err:
            self.status("Failed: %s" % err)
            gui.MessageDialog("Could not prepare '%s':\n\n%s" % (it.asset.name, err))
            return
        try:
            doc = c4d.documents.GetActiveDocument()
            msg = importer.import_result(doc, it.asset, result, self.s)
            self.status(msg)
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            _log.log("import failed: %r" % (e,))
            self.status("Import failed: %s" % e)
            gui.MessageDialog("Import failed:\n\n%s" % e)
        it.ready = True
        self.refresh_local_count()
        self.relabel_res()
        self.refresh_disk()
        self.update_info()
        self.grid.Redraw()
        self.side.Redraw()

    # ------------------------------------------------------------ events
    def set_asset_type(self, t):
        if t == self.asset_type:
            return
        self.asset_type = t
        self.s.set("last_type", t)
        self.category = None
        self.expanded.clear()
        self.SetInt32(ID_SORT, 0)
        self.refresh_local_count()
        self.load_categories()
        self.side.Redraw()
        self.start_search()

    def Command(self, cid, msg):
        if cid == ID_TYPE:
            self.set_asset_type(TYPES.get(self.GetInt32(ID_TYPE), "hdr"))
        elif cid == ID_SORT:
            idx = self.GetInt32(ID_SORT)
            if idx == len(SORT_LIST) - 1:
                self.category = DOWNLOADS
            elif self.category == DOWNLOADS:
                self.category = None
            self.side.Redraw()
            self.start_search()
        elif cid == ID_PRICE:
            idx = self.GetInt32(ID_PRICE)
            self.price = PRICE_LIST[idx][0] if 0 <= idx < len(PRICE_LIST) else "all"
            self.start_search()
        elif cid == ID_SEARCH:
            self._search_due = time.time() + 0.6
        elif cid == ID_ZOOM:
            v = self.GetInt32(ID_ZOOM)
            if v != self.cell_w:
                cols, cw, ch = self.grid.layout()
                first = int(self.grid.scroll // ch) * cols
                self.cell_w = v
                self.round_cache.clear()
                self.s.set("preview_size", v)
                cols, cw, ch = self.grid.layout()
                self.grid.scroll = (first // cols) * ch
                self.grid.clamp()
                self.grid.Redraw()
        elif cid == ID_RES:
            res = self.current_res()
            if res:
                self.s.set("resolution_pref", res)
            self.refresh_disk()
            self.update_info()
        elif cid == ID_DISK:
            self.choose_disk()
        elif cid == ID_DELETE:
            self.delete_selected_file()
        elif cid == ID_TARGET:
            idx = self.GetInt32(ID_TARGET)
            if 0 <= idx < len(ENGINES):
                self.s.set("renderer", ENGINES[idx][0])
        elif cid == ID_BTN_LOGIN:
            self.do_login()
        elif cid == ID_BTN_SETTINGS:
            dlg = SettingsDialog(self.s, self.client)
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=560, defaulth=260)
            self.SetString(ID_FOLDER, pipeline.cache_root(self.s))
        elif cid == ID_OPENSITE:
            webbrowser.open(api.WEB_BASE)
        elif cid == ID_BROWSE:
            p = c4d.storage.LoadDialog(c4d.FILESELECT_DIRECTORY, "Choose download folder",
                                       def_path=self.GetString(ID_FOLDER))
            if p:
                self.SetString(ID_FOLDER, p)
                self.s.set("cache_dir", p)
                self.refresh_local_count()
                self.start_search()
        elif cid == ID_RETRY:
            folder = self.GetString(ID_FOLDER).strip()
            if folder:
                self.s.set("cache_dir", folder, False)
            self.s.save()
            self.categories.pop(self.asset_type, None)
            self.load_categories()
            self.start_search()
        elif cid == ID_DOWNLOAD:
            self.start_download()
        return True

    def Timer(self, msg):
        if licensenotice.is_showing():
            return
        hdri_build.pending_tick()
        self.runner.pump()
        if self._drop is not None:
            self.finish_drop()
        if self._search_due and time.time() >= self._search_due:
            self._search_due = None
            self.start_search()
        if self.busy:
            self.SetString(ID_STATUS, self.progress_text)
