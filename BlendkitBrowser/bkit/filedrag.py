# -*- coding: utf-8 -*-
"""Drag a *real* file out of the browser with the Windows shell (OLE drag and drop).

``GeUserArea.HandleMouseDrag`` can only create Cinema 4D internal drag types. The
viewport rejects ``DRAGTYPE_FILENAME_OTHER`` for scene files, so a downloaded model
could never be dropped there even though the payload was the file on disk.

This module hands the downloaded file itself to the Windows shell
(``SHCreateDataObject`` + ``ole32.DoDragDrop``). Cinema 4D then receives exactly the
same drop as a file dragged out of Explorer, and its own importer handles the file.
The drag starts from the real downloaded file in its folder, so the drop payload is
literally that file.

Only models use this path. HDRIs and textures keep the native drag, because image
fields in Cinema 4D accept those directly.

Everything is guarded: on macOS, or when OLE cannot be initialised, :func:`start_drag`
returns ``False`` and the caller falls back to ``HandleMouseDrag``.
"""
import ctypes
import os
import time

S_OK = 0
E_NOINTERFACE = 0x80004002
E_POINTER = 0x80004003
DRAGDROP_S_DROP = 0x00040100
DRAGDROP_S_CANCEL = 0x00040101
DRAGDROP_S_USEDEFAULTCURSORS = 0x00040102
DROPEFFECT_COPY = 1
MK_LBUTTON = 0x0001
VK_LBUTTON = 0x01
VK_SHIFT = 0x10
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002

DRAG_THRESHOLD = 4        # pixels of movement before a click becomes a drag
POLL = 0.006              # seconds between mouse polls
MAX_WAIT = 20.0           # never block Cinema 4D for longer than this

HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
DWORD = ctypes.c_ulong
BOOL = ctypes.c_int
LPVOID = ctypes.c_void_p

# WINFUNCTYPE only exists on Windows; the module must still import everywhere.
_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


_QI = _FUNCTYPE(HRESULT, LPVOID, ctypes.POINTER(GUID), ctypes.POINTER(LPVOID))
_ADDREF = _FUNCTYPE(ULONG, LPVOID)
_RELEASE = _FUNCTYPE(ULONG, LPVOID)
_QCD = _FUNCTYPE(HRESULT, LPVOID, BOOL, DWORD)
_GF = _FUNCTYPE(HRESULT, LPVOID, DWORD)


class _DropSourceVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI),
                ("AddRef", _ADDREF),
                ("Release", _RELEASE),
                ("QueryContinueDrag", _QCD),
                ("GiveFeedback", _GF)]


class _DropSource(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_DropSourceVtbl))]


_SOURCES = {}
_CTX = None
_CTX_ERROR = ""
_OLE_READY = False
# True when the last start_drag() actually entered the shell drag loop (not a click).
last_dragged = False

IID_IDATAOBJECT = "{0000010E-0000-0000-C000-000000000046}"
IID_IDROPSOURCE = "{00000121-0000-0000-C000-000000000046}"
IID_IUNKNOWN = "{00000000-0000-0000-C000-000000000046}"


def _note(log, msg):
    try:
        if log is not None:
            log(msg)
        else:
            print("[file drag] " + msg)
    except Exception:
        pass


def available():
    """True when a real file drag can be started on this platform."""
    return _load() is not None and _init_ole(_load())


def last_error():
    return _CTX_ERROR


# ---------------------------------------------------------------- Win32 plumbing
def _load():
    global _CTX, _CTX_ERROR
    if _CTX is not None:
        return _CTX
    if os.name != "nt":
        _CTX_ERROR = "file drag needs Windows"
        return None
    try:
        from ctypes import wintypes
        ole32 = ctypes.WinDLL("ole32")
        shell32 = ctypes.WinDLL("shell32")
        user32 = ctypes.WinDLL("user32")

        ole32.OleInitialize.argtypes = [LPVOID]
        ole32.OleInitialize.restype = HRESULT
        ole32.DoDragDrop.argtypes = [LPVOID, LPVOID, DWORD, ctypes.POINTER(DWORD)]
        ole32.DoDragDrop.restype = HRESULT
        ole32.CoTaskMemFree.argtypes = [LPVOID]
        ole32.CoTaskMemFree.restype = None
        ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
        ole32.CLSIDFromString.restype = HRESULT

        shell32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, LPVOID, ctypes.POINTER(LPVOID),
                                               wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        shell32.SHParseDisplayName.restype = HRESULT
        shell32.SHCreateDataObject.argtypes = [LPVOID, ctypes.c_uint, ctypes.POINTER(LPVOID),
                                               LPVOID, ctypes.POINTER(GUID),
                                               ctypes.POINTER(LPVOID)]
        shell32.SHCreateDataObject.restype = HRESULT
        shell32.ILFindLastID.argtypes = [LPVOID]
        shell32.ILFindLastID.restype = LPVOID

        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, DWORD, ctypes.c_size_t]
        user32.keybd_event.restype = None
    except Exception as e:  # noqa
        _CTX_ERROR = "cannot load the Windows shell: %r" % (e,)
        return None
    _CTX = {"wintypes": wintypes, "ole32": ole32, "shell32": shell32, "user32": user32}
    return _CTX


def _init_ole(ctx):
    global _OLE_READY, _CTX_ERROR
    if _OLE_READY:
        return True
    if ctx is None:
        return False
    try:
        hr = ctx["ole32"].OleInitialize(None)
    except Exception as e:  # noqa
        _CTX_ERROR = "OleInitialize failed: %r" % (e,)
        return False
    if hr not in (0, 1):        # S_OK or S_FALSE (already initialised)
        _CTX_ERROR = "OleInitialize 0x%08x" % (hr & 0xffffffff)
        return False
    _OLE_READY = True
    return True


def _guid(ctx, text):
    g = GUID()
    if ctx["ole32"].CLSIDFromString(text, ctypes.byref(g)) != S_OK:
        raise OSError("CLSIDFromString(%s)" % text)
    return g


def _guid_bytes(g):
    return bytes(ctypes.string_at(ctypes.byref(g), ctypes.sizeof(GUID)))


def _address(ptr):
    return ptr.value if isinstance(ptr, ctypes.c_void_p) else int(ptr)


def _call(ptr, index, restype, argtypes=(), args=()):
    """Call vtable slot *index* of the COM interface at *ptr*."""
    addr = _address(ptr)
    if not addr:
        raise OSError("null COM pointer")
    vtbl = ctypes.cast(addr, ctypes.POINTER(ctypes.POINTER(LPVOID)))[0]
    fn_addr = vtbl[index]
    proto = _FUNCTYPE(restype, LPVOID, *argtypes)
    return proto(fn_addr)(LPVOID(addr), *args)


def _release(ptr):
    return _call(ptr, 2, ULONG)


def _cursor(ctx):
    p = ctx["wintypes"].POINT()
    if not ctx["user32"].GetCursorPos(ctypes.byref(p)):
        return None
    return int(p.x), int(p.y)


def _down(ctx, vk):
    return bool(ctx["user32"].GetAsyncKeyState(vk) & 0x8000)


def _key(ctx, vk, down):
    """Synthesise a key press/release (used to hold Shift during the drop)."""
    try:
        ctx["user32"].keybd_event(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0)
        return True
    except Exception:  # noqa
        return False


def _data_object(ctx, path):
    """IDataObject for *path* (the same object Explorer builds for a file)."""
    shell32 = ctx["shell32"]
    ole32 = ctx["ole32"]
    pidl_full = LPVOID()
    pidl_dir = LPVOID()
    hr = shell32.SHParseDisplayName(path, None, ctypes.byref(pidl_full), 0, None)
    if hr != S_OK or not pidl_full.value:
        raise OSError("SHParseDisplayName(%s) 0x%08x" % (path, hr & 0xffffffff))
    try:
        folder = os.path.dirname(path)
        hr = shell32.SHParseDisplayName(folder, None, ctypes.byref(pidl_dir), 0, None)
        if hr != S_OK or not pidl_dir.value:
            raise OSError("SHParseDisplayName(%s) 0x%08x" % (folder, hr & 0xffffffff))
        child = shell32.ILFindLastID(pidl_full)
        arr = (LPVOID * 1)(child)
        pdo = LPVOID()
        iid = _guid(ctx, IID_IDATAOBJECT)
        hr = shell32.SHCreateDataObject(pidl_dir, 1, arr, None,
                                        ctypes.byref(iid), ctypes.byref(pdo))
        if hr != S_OK or not pdo.value:
            raise OSError("SHCreateDataObject 0x%08x" % (hr & 0xffffffff))
        return pdo
    finally:
        if pidl_full.value:
            ole32.CoTaskMemFree(pidl_full)
        if pidl_dir.value:
            ole32.CoTaskMemFree(pidl_dir)


class _Source(object):
    """Minimal IDropSource: keeps the drag going while the left button is down."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.refs = 1
        self.vtbl = _DropSourceVtbl()
        self.vtbl.QueryInterface = _QI(self._query_interface)
        self.vtbl.AddRef = _ADDREF(self._add_ref)
        self.vtbl.Release = _RELEASE(self._release)
        self.vtbl.QueryContinueDrag = _QCD(self._query_continue_drag)
        self.vtbl.GiveFeedback = _GF(self._give_feedback)
        self.obj = _DropSource()
        self.obj.lpVtbl = ctypes.pointer(self.vtbl)
        self.addr = ctypes.addressof(self.obj)
        self.iid_unknown = _guid_bytes(_guid(ctx, IID_IUNKNOWN))
        self.iid_source = _guid_bytes(_guid(ctx, IID_IDROPSOURCE))
        _SOURCES[self.addr] = self

    # IUnknown ------------------------------------------------------------
    def _query_interface(self, this, riid, ppv):
        try:
            if not ppv:
                return E_POINTER
            want = bytes(ctypes.string_at(riid, ctypes.sizeof(GUID))) if riid else b""
            if want and want in (self.iid_unknown, self.iid_source):
                self.refs += 1
                ppv[0] = this
                return S_OK
            ppv[0] = None
            return E_NOINTERFACE
        except Exception:  # noqa
            return E_NOINTERFACE

    def _add_ref(self, this):
        self.refs += 1
        return self.refs

    def _release(self, this):
        self.refs -= 1
        if self.refs <= 0:
            _SOURCES.pop(self.addr, None)
            return 0
        return self.refs

    # IDropSource ---------------------------------------------------------
    def _query_continue_drag(self, this, escape_pressed, key_state):
        try:
            if escape_pressed:
                return DRAGDROP_S_CANCEL
            if not (key_state & MK_LBUTTON):
                return DRAGDROP_S_DROP
            return S_OK
        except Exception:  # noqa
            return DRAGDROP_S_CANCEL

    def _give_feedback(self, this, effect):
        return DRAGDROP_S_USEDEFAULTCURSORS


# ------------------------------------------------------------------- public API
def _wait_for_drag(ctx):
    """Block until the press turns into a drag. False = the user only clicked."""
    start = _cursor(ctx)
    moved = 0
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        if _down(ctx, VK_ESCAPE):
            return False
        if not _down(ctx, VK_LBUTTON):
            return False
        pos = _cursor(ctx)
        if pos:
            if start is None:
                start = pos
            moved += abs(pos[0] - start[0]) + abs(pos[1] - start[1])
            start = pos
            if moved >= DRAG_THRESHOLD:
                return True
        time.sleep(POLL)
    return False


def start_drag(paths, log=None):
    """Drag the first existing file in *paths* with the Windows shell.

    Blocks while the user drags (like ``HandleMouseDrag``). Returns ``True`` when the
    gesture was handled here - either a real drag or a plain click with no movement -
    and ``False`` when the shell drag is unavailable and the caller should fall back
    to Cinema 4D's native drag. Never raises.
    """
    global last_dragged
    last_dragged = False
    try:
        ctx = _load()
        if ctx is None or not _init_ole(ctx):
            _note(log, "shell drag unavailable: %s" % _CTX_ERROR)
            return False
        files = [p for p in (paths or []) if p and os.path.isfile(p)]
        if not files:
            _note(log, "shell drag: no downloaded file to drag")
            return False
        path = os.path.abspath(files[0])
        if not _wait_for_drag(ctx):
            return True                     # a normal click, nothing dragged
        pdo = None
        src = None
        held = False
        try:
            pdo = _data_object(ctx, path)
            src = _Source(ctx)
            # Hold Shift during the whole drag: Cinema 4D then merges the dropped file
            # into the open document instead of opening a new one.
            if not _down(ctx, VK_SHIFT):
                held = _key(ctx, VK_SHIFT, True)
                time.sleep(0.02)
            effect = DWORD(DROPEFFECT_COPY)
            last_dragged = True
            hr = ctx["ole32"].DoDragDrop(pdo, ctypes.byref(src.obj),
                                         DROPEFFECT_COPY, ctypes.byref(effect))
            _note(log, "dragged '%s' (0x%08x, effect %d)"
                  % (os.path.basename(path), hr & 0xffffffff, effect.value))
            return True
        finally:
            if held:
                _key(ctx, VK_SHIFT, False)
            if src is not None:
                _SOURCES.pop(src.addr, None)
            if pdo is not None:
                try:
                    _release(pdo)
                except Exception:  # noqa
                    pass
    except Exception as e:  # noqa
        _note(log, "shell drag failed: %r" % (e,))
        return False
