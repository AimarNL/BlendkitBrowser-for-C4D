# -*- coding: utf-8 -*-
"""Blendkit (ex-BlenderKit) REST client, stdlib only.

Endpoints follow the public BlenderKit add-on conventions:
  GET  /api/v1/me/                 (Authorization: Bearer <api key>)
  GET  /api/v1/search/?query=...   asset search
  GET  /api/v1/categories/         category tree
  GET  <file.downloadUrl>?scene_uuid=...  -> {"filePath": "<signed url>"}
If the real API differs, use Settings > Diagnostics to dump the raw responses.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import log as _log

UA = "BlendkitC4D/0.1 (Cinema 4D plugin)"
WEB_BASE = "https://www.blendkit.com"      # where every browser link goes
FALLBACK_BASES = ("https://www.blendkit.com", "https://www.blenderkit.com")

ORDERS = [
    ("Latest", "-created"),
    ("Relevance", "_score"),
    ("Top rated", "-rating_quality"),
]


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _res_key(label):
    m = re.match(r"^(\d+(?:\.\d+)?)K$", label, re.I)
    return float(m.group(1)) if m else 99999.0


class Asset:
    def __init__(self, raw):
        self.raw = raw
        self.id = str(raw.get("id") or "")
        self.base_id = str(raw.get("assetBaseId") or self.id)
        self.key = self.base_id
        self.name = raw.get("name") or "Unnamed"
        self.type = (raw.get("assetType") or "").lower()
        self.description = raw.get("description") or ""
        self.is_free = raw.get("isFree")
        self.can_download = raw.get("canDownload")
        a = raw.get("author")
        if isinstance(a, dict):
            nm = ("%s %s" % (a.get("firstName", ""), a.get("lastName", ""))).strip()
            self.author = nm or a.get("fullName") or a.get("username") or ""
        else:
            self.author = str(a or "")
        self.thumb_url = (raw.get("thumbnailMiddleUrl") or raw.get("thumbnailSmallUrl")
                          or raw.get("thumbnailLargeUrl") or "")
        self.files = [f for f in (raw.get("files") or []) if isinstance(f, dict)]

    def is_locked(self):
        return self.can_download is False

    def access_key(self):
        r = self.raw
        return "isFree=%s access=%s label=%s forSale=%s price=%s" % (
            self.is_free, r.get("access"), r.get("accessLabel"), r.get("isForSale"), r.get("basePrice"))

    def is_pro(self):
        if self.is_free is False:
            return True
        label = ("%s %s" % (self.raw.get("accessLabel") or "", self.raw.get("access") or "")).lower()
        if any(k in label for k in ("full", "paid", "premium", "pro ", "pro")) and "free" not in label:
            return True
        return self.is_free is None and self.can_download is False

    def resolutions(self):
        """[(label, file_dict)] ordered small -> large, 'Original' last."""
        out = []
        for f in self.files:
            ft = f.get("fileType") or ""
            if ft == "blend":
                out.append(("Original", f))
            elif ft.startswith("resolution_"):
                out.append((ft[len("resolution_"):].replace("_", ".").upper(), f))
        out.sort(key=lambda t: _res_key(t[0]))
        if not out:
            for f in self.files:
                if (f.get("downloadUrl") or f.get("url")) and f.get("fileType") != "thumbnail":
                    out.append(("Original", f))
                    break
        return out

    def file_for(self, label):
        for lab, f in self.resolutions():
            if lab == label:
                return f
        return None

    def web_url(self, base):
        return "%s/asset-gallery-detail/%s/" % (base.rstrip("/"), self.id or self.base_id)


def norm_category(c):
    count = c.get("assetCountCumulative")
    if count is None:
        count = c.get("assetCount", 0)
    return {
        "name": c.get("name") or c.get("slug") or "?",
        "slug": c.get("slug") or c.get("name"),
        "count": count or 0,
        "children": sorted([norm_category(x) for x in (c.get("children") or [])],
                           key=lambda x: x["name"].lower()),
    }


def categories_for_type(results, asset_type):
    for c in results:
        nm = (c.get("name") or "").lower()
        if nm in (asset_type, asset_type + "s") or (c.get("slug") or "").lower() == asset_type:
            return [norm_category(x) for x in (c.get("children") or [])]
    return [norm_category(x) for x in results]


class Client:
    def __init__(self, settings):
        self.s = settings
        self.scene_uuid = str(uuid.uuid4())
        self.active_base = None

    # ---------- plumbing ----------
    def bases(self):
        out = []
        for b in [self.active_base, (self.s.get("api_base") or "").rstrip("/")] + list(FALLBACK_BASES):
            if b and b not in out:
                out.append(b)
        return out

    def _opener(self):
        return urllib.request.build_opener()

    def _headers(self, auth):
        h = {"User-Agent": UA, "Accept": "application/json"}
        key = (self.s.get("api_key") or "").strip()
        if auth and key:
            h["Authorization"] = "Bearer " + key
        return h

    def _open(self, url, auth=True, timeout=30, _retry=True):
        req = urllib.request.Request(url, headers=self._headers(auth))
        try:
            return self._opener().open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(300).decode("utf-8", "replace")
            except Exception:
                pass
            raise ApiError("HTTP %d: %s %s" % (e.code, url.split("?")[0], body), e.code)
        except (urllib.error.URLError, OSError) as e:
            if _retry:
                _log.log("network error, retrying once: %s (%s)" % (e, url.split("?")[0]))
                time.sleep(0.6)
                return self._open(url, auth, timeout, _retry=False)
            reason = getattr(e, "reason", e)
            raise ApiError("Network error: %s" % (reason,))

    @staticmethod
    def _json(resp):
        with resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_json(self, path_or_url, auth=True, timeout=30):
        if path_or_url.startswith("http"):
            return self._json(self._open(path_or_url, auth, timeout))
        last = None
        for base in self.bases():
            try:
                data = self._json(self._open(base + path_or_url, auth, timeout))
                self.active_base = base
                return data
            except ApiError as e:
                last = e
                _log.log("API %s failed: %s" % (base, e))
                if e.status in (401, 403):
                    raise
            except ValueError as e:
                last = ApiError("Invalid JSON from %s: %s" % (base, e))
        raise last or ApiError("No API base reachable")

    # ---------- high level ----------
    def me(self):
        return self.get_json("/api/v1/me/")

    @staticmethod
    def user_label(me):
        u = me.get("user") if isinstance(me.get("user"), dict) else me
        nm = ("%s %s" % (u.get("firstName", ""), u.get("lastName", ""))).strip()
        return nm or u.get("username") or u.get("email") or "account"

    def search_path(self, asset_type, keywords="", category=None, order="-created",
                    free_only=False, page_size=40, price=None):
        terms = [urllib.parse.quote(w) for w in (keywords or "").split()]
        terms.append("asset_type:%s" % asset_type)
        if category:
            terms.append("category_subtree:%s" % category)
        if free_only or price == "free":
            terms.append("is_free:true")
        elif price == "pro":
            terms.append("is_free:false")
        if order:
            terms.append("order:%s" % order)
        return "/api/v1/search/?query=%s&page_size=%d" % ("+".join(terms), page_size)

    def search(self, path_or_url):
        data = self.get_json(path_or_url)
        assets = [Asset(r) for r in (data.get("results") or []) if isinstance(r, dict)]
        return assets, data.get("next"), data.get("count")

    def categories(self, asset_type):
        data = self.get_json("/api/v1/categories/")
        results = data.get("results") if isinstance(data, dict) else data
        return categories_for_type(results or [], asset_type)

    def get_download_url(self, file_dict):
        url = file_dict.get("downloadUrl") or file_dict.get("url")
        if not url:
            raise ApiError("File entry has no download URL")
        url += ("&" if "?" in url else "?") + "scene_uuid=" + self.scene_uuid
        data = self.get_json(url)
        real = data.get("filePath") or data.get("url") or data.get("downloadUrl")
        if not real:
            raise ApiError("Download link missing in response: %s" % json.dumps(data)[:200])
        return real

    def download_file(self, url, dest, progress=None, auth=False):
        tmp = dest + ".part"
        resp = self._open(url, auth=auth, timeout=60)
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        os.replace(tmp, dest)
        return dest

    def download_thumb(self, url, base_path):
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        resp = self._open(url, auth=False, timeout=30)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ctype.split(";")[0].strip())
        if not ext:
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or ".jpg"
        dest = base_path + ext
        with resp, open(dest, "wb") as f:
            f.write(resp.read())
        return dest

    def dump_diagnostics(self, directory):
        os.makedirs(directory, exist_ok=True)
        out = []
        jobs = [
            ("me", "/api/v1/me/"),
            ("categories", "/api/v1/categories/"),
            ("search_hdr", self.search_path("hdr", page_size=5)),
            ("search_material", self.search_path("material", page_size=5)),
            ("search_model", self.search_path("model", page_size=5)),
        ]
        for name, path in jobs:
            fp = os.path.join(directory, name + ".json")
            try:
                data = self.get_json(path)
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                out.append("%s: OK" % name)
            except Exception as e:  # noqa
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(str(e))
                out.append("%s: %s" % (name, e))
        return out
