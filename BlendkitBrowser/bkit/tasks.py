# -*- coding: utf-8 -*-
"""Worker pool. Callbacks are always executed on the main thread via pump()."""
import queue
from concurrent.futures import ThreadPoolExecutor

from . import log as _log


class TaskRunner:
    def __init__(self, workers=6):
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.q = queue.Queue()

    def submit(self, fn, on_done=None):
        def run():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa
                res, err = None, e
                _log.log("task error: %r" % (e,))
            self.q.put((on_done, res, err))
        self.pool.submit(run)

    def pump(self, limit=50):
        n = 0
        while n < limit:
            try:
                cb, res, err = self.q.get_nowait()
            except queue.Empty:
                break
            n += 1
            if cb:
                try:
                    cb(res, err)
                except Exception as e:  # noqa
                    _log.log("callback error: %r" % (e,))
        return n
