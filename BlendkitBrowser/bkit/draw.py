# -*- coding: utf-8 -*-
"""Drawing helpers and scroll area, copied 1:1 from the Poly Haven HDRI Browser so both plugins look and behave the same."""
import math
import os
import re
import struct

import c4d
from c4d import gui, bitmaps

SB_W = 12                       # scrollbar width
CELL_W = 250


def V(r, g=None, b=None):
    if g is None:
        g = b = r
    return c4d.Vector(r, g, b)


def _corner_insets(r):
    out = []
    for i in range(r):
        dy = r - i - 0.5
        out.append(int(round(r - math.sqrt(max(0.0, r * r - dy * dy)))))
    return out


def _rgb(c):
    """c4d.Vector (0..1) -> (r, g, b) ints 0..255"""
    return (int(round(c.x * 255)), int(round(c.y * 255)), int(round(c.z * 255)))


def _coverage(i, j, r, corner, ss=4, rad=None):
    """Fraction (0..1) of pixel (i, j) of an r x r corner tile that lies inside the
    rounded shape (circle radius rad, default r). corner: 0 top-left, 1 top-right,
    2 bottom-left, 3 bottom-right."""
    rad = r if rad is None else rad
    ii = i if corner in (0, 2) else r - 1 - i
    jj = j if corner in (0, 1) else r - 1 - j
    cnt = 0
    for sy in range(ss):
        for sx in range(ss):
            px = ii + (sx + 0.5) / ss
            py = jj + (sy + 0.5) / ss
            if (px - r) ** 2 + (py - r) ** 2 <= rad * rad:
                cnt += 1
    return cnt / float(ss * ss)


_SPRITES = {}


def _corner_sprite(corner, r, fill, bg):
    """Small anti-aliased bitmap: shape colour blended with the background colour."""
    key = (corner, r, fill, bg)
    spr = _SPRITES.get(key)
    if spr is None:
        spr = bitmaps.BaseBitmap()
        spr.Init(r, r, 24)
        for j in range(r):
            for i in range(r):
                cov = _coverage(i, j, r, corner)
                spr.SetPixel(i, j, *[int(round(bg[k] * (1.0 - cov) + fill[k] * cov)) for k in range(3)])
        _SPRITES[key] = spr
    return spr


def fill_round(ua, x1, y1, x2, y2, r, col, bg=None):
    """Filled rounded rectangle. With 'bg' (the colour it is drawn on) the corners are
    anti-aliased; without it they are stepped."""
    r = max(0, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    ua.DrawSetPen(col)
    if r < 2:
        ua.DrawRectangle(x1, y1, x2, y2)
        return
    if bg is not None:
        try:
            ua.DrawRectangle(x1 + r, y1, x2 - r, y2)                 # middle column
            ua.DrawRectangle(x1, y1 + r, x1 + r - 1, y2 - r)         # left strip
            ua.DrawRectangle(x2 - r + 1, y1 + r, x2, y2 - r)         # right strip
            f, b = _rgb(col), _rgb(bg)
            for corner, (px, py) in enumerate(((x1, y1), (x2 - r + 1, y1),
                                               (x1, y2 - r + 1), (x2 - r + 1, y2 - r + 1))):
                spr = _corner_sprite(corner, r, f, b)
                ua.DrawBitmap(spr, px, py, r, r, 0, 0, r, r, c4d.BMP_NORMALSCALED)
            return
        except Exception as e:
            print("[Blendkit] rounded corners: %s" % e)
    for i, inset in enumerate(_corner_insets(r)):
        ua.DrawRectangle(x1 + inset, y1 + i, x2 - inset, y1 + i)
        ua.DrawRectangle(x1 + inset, y2 - i, x2 - inset, y2 - i)
    ua.DrawRectangle(x1, y1 + r, x2, y2 - r)


_RINGS = {}


def _ring_sprite(corner, ro, bw, ring, inner, bg):
    key = (corner, ro, bw, ring, inner, bg)
    spr = _RINGS.get(key)
    if spr is None:
        spr = bitmaps.BaseBitmap()
        spr.Init(ro, ro, 24)
        for j in range(ro):
            for i in range(ro):
                co = _coverage(i, j, ro, corner)                      # outer outline
                ci = _coverage(i, j, ro, corner, rad=ro - bw)         # inner outline
                px = []
                for k in range(3):
                    shape = ring[k] * (1.0 - ci) + inner[k] * ci
                    px.append(int(round(bg[k] * (1.0 - co) + shape * co)))
                spr.SetPixel(i, j, *px)
        _RINGS[key] = spr
    return spr


def fill_round_ring(ua, x1, y1, x2, y2, ro, bw, ring, inner, bg):
    """Rounded rectangle with a border of width bw (colour 'ring') around an inner
    fill, drawn on background 'bg', all corners anti-aliased."""
    ro = max(0, min(ro, (x2 - x1) // 2, (y2 - y1) // 2))
    if ro < 3 or bw >= ro:
        fill_round(ua, x1, y1, x2, y2, ro, ring, bg)
        return
    try:
        ua.DrawSetPen(ring)
        ua.DrawRectangle(x1 + ro, y1, x2 - ro, y1 + bw - 1)
        ua.DrawRectangle(x1 + ro, y2 - bw + 1, x2 - ro, y2)
        ua.DrawRectangle(x1, y1 + ro, x1 + bw - 1, y2 - ro)
        ua.DrawRectangle(x2 - bw + 1, y1 + ro, x2, y2 - ro)
        ua.DrawSetPen(inner)
        ua.DrawRectangle(x1 + ro, y1 + bw, x2 - ro, y2 - bw)
        ua.DrawRectangle(x1 + bw, y1 + ro, x1 + ro - 1, y2 - ro)
        ua.DrawRectangle(x2 - ro + 1, y1 + ro, x2 - bw, y2 - ro)
        fr, fi, fb = _rgb(ring), _rgb(inner), _rgb(bg)
        for corner, (px, py) in enumerate(((x1, y1), (x2 - ro + 1, y1),
                                           (x1, y2 - ro + 1), (x2 - ro + 1, y2 - ro + 1))):
            spr = _ring_sprite(corner, ro, bw, fr, fi, fb)
            ua.DrawBitmap(spr, px, py, ro, ro, 0, 0, ro, ro, c4d.BMP_NORMALSCALED)
    except Exception as e:
        print("[Blendkit] rounded border: %s" % e)


def draw_dot(ua, x, y, d, on, bg):
    """Status circle like the dots in the C4D managers: green + filled = on,
    dark grey empty outline = off. d = diameter (even), (x, y) = top-left corner."""
    r = d // 2
    if on:
        ring, inner = _rgb(V(0.14, 0.52, 0.28)), _rgb(V(0.30, 0.82, 0.44))
    else:
        ring, inner = _rgb(V(0.36)), _rgb(V(0.13))
    b = _rgb(bg)
    try:
        for corner, (px, py) in enumerate(((x, y), (x + r, y), (x, y + r), (x + r, y + r))):
            spr = _ring_sprite(corner, r, 2, ring, inner, b)
            ua.DrawBitmap(spr, px, py, r, r, 0, 0, r, r, c4d.BMP_NORMALSCALED)
    except Exception as e:
        print("[Blendkit] status dot: %s" % e)


def rounded_copy(bmp, tw, th, r, bg):
    """Copy of a thumbnail scaled to tw x th with anti-aliased rounded corners
    (corner pixels blended with the card colour 'bg')."""
    dst = bitmaps.BaseBitmap()
    dst.Init(tw, th, 24)
    bmp.ScaleIt(dst, 256, True, False)
    r = max(0, min(r, tw // 2, th // 2))
    b = _rgb(bg)
    for corner, (ox, oy) in enumerate(((0, 0), (tw - r, 0), (0, th - r), (tw - r, th - r))):
        for j in range(r):
            for i in range(r):
                cov = _coverage(i, j, r, corner)
                if cov >= 1.0:
                    continue
                x, y = ox + i, oy + j
                px = dst.GetPixel(x, y)
                dst.SetPixel(x, y, *[int(round(b[k] * (1.0 - cov) + px[k] * cov)) for k in range(3)])
    return dst


def cut_corners(ua, x1, y1, x2, y2, r, bg):
    """Stepped fallback: paint the background colour over the corner pixels."""
    r = max(0, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    if r < 2:
        return
    ua.DrawSetPen(bg)
    for i, inset in enumerate(_corner_insets(r)):
        if inset <= 0:
            continue
        for yy in (y1 + i, y2 - i):
            ua.DrawRectangle(x1, yy, x1 + inset - 1, yy)
            ua.DrawRectangle(x2 - inset + 1, yy, x2, yy)


C_MAIN = V(0.165)
C_SIDE = V(0.125)
C_CARD = V(0.205)
C_BADGE = V(0.27)
C_CHIP = V(0.20)
C_PURPLE = V(0.72, 0.42, 1.0)
C_PURPLE_D = V(0.45, 0.25, 0.68)
C_TEXT = V(0.88)
C_DIM = V(0.55)
C_WHITE = V(1.0)


def fmt_bytes(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    if n >= 1024 ** 3:
        return "%.2f GB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MB" % (n / 1024 ** 2)
    return "%.0f KB" % (n / 1024)


def read_image_size(path):
    """(width, height) of a .hdr / .exr read from its header only, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read(65536)
        if path.lower().endswith(".hdr"):
            m = re.search(rb"[-+]Y\s+(\d+)\s+[-+]X\s+(\d+)", data)
            if m:
                return int(m.group(2)), int(m.group(1))
        elif data[:4] == b"\x76\x2f\x31\x01":
            pos = 8
            while pos < len(data):
                end = data.index(b"\x00", pos)
                if end == pos:
                    break
                name = data[pos:end].decode("latin-1")
                pos = end + 1
                end = data.index(b"\x00", pos)
                pos = end + 1
                size = struct.unpack("<i", data[pos:pos + 4])[0]
                pos += 4
                val = data[pos:pos + size]
                pos += size
                if name == "dataWindow":
                    x0, y0, x1, y1 = struct.unpack("<4i", val[:16])
                    return x1 - x0 + 1, y1 - y0 + 1
    except Exception:
        pass
    return None


def describe_file(path):
    """'4096 x 2048, 21.3 MB' for a file on disk."""
    try:
        size = fmt_bytes(os.path.getsize(path))
    except Exception:
        size = "?"
    wh = read_image_size(path)
    return ("%d x %d, %s" % (wh[0], wh[1], size)) if wh else size




class ScrollArea(gui.GeUserArea):
    """User area with a vertical scroll offset and a draggable scrollbar."""

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.scroll = 0

    # to override
    def content_height(self):
        return 0

    def Sized(self, w, h):
        """Window was resized: keep the scroll position valid and repaint the whole area."""
        self.clamp()
        self.Redraw()

    def begin_draw(self, x1, y1, x2, y2):
        """Double-buffer and clip drawing to the area (prevents drawing over neighbouring controls)."""
        self.OffScreenOn()
        self.SetClippingRegion(x1, y1, x2, y2)

    def area_h(self):
        return max(self.GetHeight(), 50)

    def area_w(self):
        return max(self.GetWidth(), CELL_W + SB_W)

    def max_scroll(self):
        return max(0, self.content_height() - self.area_h())

    def clamp(self):
        self.scroll = max(0, min(int(self.scroll), self.max_scroll()))

    def thumb(self):
        H, ch = self.area_h(), self.content_height()
        if ch <= H:
            return None
        th = max(30, int(H * H / ch))
        ty = int((H - th) * self.scroll / float(ch - H))
        return ty, th

    def draw_scrollbar(self):
        """Slim Cinema 4D-style scrollbar: dark track, rounded grey thumb."""
        W, H = self.area_w(), self.area_h()
        track = V(0.135)
        self.DrawSetPen(track)
        self.DrawRectangle(W - SB_W, 0, W, H)
        t = self.thumb()
        if t:
            ty, th = t
            fill_round(self, W - SB_W + 3, ty + 2, W - 3, ty + th - 2, 3, V(0.40), track)

    def scrollbar_click(self, mx, my):
        t = self.thumb()
        if not t:
            return
        ty, th = t
        H = self.area_h()
        if my < ty or my > ty + th:                      # click on the track: page jump
            self.scroll += (H * 0.9) if my > ty else -(H * 0.9)
            self.clamp()
            self.after_scroll()
            return
        ratio = (self.content_height() - H) / float(max(1, H - th))
        self.MouseDragStart(c4d.BFM_INPUT_MOUSELEFT, mx, my,
                            c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE | c4d.MOUSEDRAGFLAGS_NOMOVE)
        while True:
            res, dx, dy, chn = self.MouseDrag()
            if res != c4d.MOUSEDRAGRESULT_CONTINUE:
                break
            self.scroll -= dy * ratio
            self.clamp()
            self.after_scroll()
        self.MouseDragEnd()

    def after_scroll(self):
        self.Redraw()


