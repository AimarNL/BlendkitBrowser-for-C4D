# -*- coding: utf-8 -*-
"""Tiny thread-safe logger: file + in-memory ring; console print only from main thread."""
import os
import threading
import time

_path = None
_lock = threading.Lock()
_ring = []


def init(directory):
    global _path
    _path = os.path.join(directory, "blendkit.log")
    try:
        if os.path.exists(_path) and os.path.getsize(_path) > 1000000:
            os.replace(_path, _path + ".old")
    except OSError:
        pass


def log_path():
    return _path


def log(msg):
    line = time.strftime("%H:%M:%S ") + str(msg)
    with _lock:
        _ring.append(line)
        del _ring[:-500]
        if _path:
            try:
                with open(_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
    if threading.current_thread() is threading.main_thread():
        print("[Blendkit] " + str(msg))


def tail(n=40):
    with _lock:
        return "\n".join(_ring[-n:])
