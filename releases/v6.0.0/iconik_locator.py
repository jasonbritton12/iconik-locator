#!/usr/bin/env python3
"""
Iconik Storage Locator v6.0.0

Fast dependency-free bidirectional locator for Iconik storage origins.

Runtime dependencies:
  - Python standard library only when run as source.
  - Packaged macOS binaries are standalone.
  - On macOS, credentials are stored in Keychain through /usr/bin/security.

Intentional scope:
  - Single asset/share/UUID lookup (Iconik → S3/storage path).
  - Reverse lookup from S3 URI back to Iconik asset URL.
  - S3, HTTPS, and FULL presigned output modes.
  - Multi-asset share handling: ERROR, FIRST, ALL.
  - Multi-source file handling: ERROR, FIRST, ALL.

XLSX support was removed to eliminate pandas/openpyxl. Export Excel-readable CSV
instead.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "6.0.1"
APP_NAME = "Iconik Storage Locator"
CONFIG_DIR = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", "IconikLocator"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
KEYCHAIN_SERVICE = "IconikLocator"
KEYCHAIN_ACCOUNT_APP_ID = "app_id"
KEYCHAIN_ACCOUNT_AUTH_TOKEN = "auth_token"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
ANY_UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)
ASSET_URL_RE = re.compile(r"/assets?/([0-9a-f-]{36})(?:/|$)", re.I)
COLLECTION_URL_RE = re.compile(r"/collections?/([0-9a-f-]{36})(?:/|$)", re.I)
SHARE_PATH_RE = re.compile(r"/shares?/([A-Za-z0-9_-]+)(?:/|$)", re.I)
SHORT_SHARE_RE = re.compile(r"/u/([A-Za-z0-9_-]+)(?:/|$)", re.I)
S3_URI_RE = re.compile(r"^s3://([^/]+)/(.*)$", re.I)

VALID_OUTPUTS = ("HTTPS", "S3", "FULL")
VALID_MULTI = ("ERROR", "FIRST", "ALL")


def is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


class UI:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._last_progress = 0.0
        self._color = is_tty()

    def _style(self, text: str, code: str) -> str:
        if not self._color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def banner(self) -> None:
        if self.quiet:
            return
        print(self._style(f"{APP_NAME} {VERSION}", "1;36"))

    def info(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def note(self, msg: str) -> None:
        if not self.quiet:
            print(self._style(msg, "2"))

    def warn(self, msg: str) -> None:
        print(self._style(f"WARNING: {msg}", "33"), file=sys.stderr)

    def err(self, msg: str) -> None:
        print(self._style(f"ERROR: {msg}", "31"), file=sys.stderr)

    def ask(self, prompt: str, default: Optional[str] = None) -> str:
        suffix = f" [{default}]" if default not in (None, "") else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        return raw

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt + ": ").strip()

    def confirm(self, prompt: str, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        raw = input(f"{prompt} [{suffix}]: ").strip().lower()
        if raw == "":
            return default
        return raw in ("y", "yes")

    def progress(self, msg: str, force: bool = False) -> None:
        if self.quiet:
            return
        now = time.time()
        if not force and (now - self._last_progress) < 0.2:
            return
        self._last_progress = now
        if is_tty():
            print("\r" + msg[:220] + " " * 10, end="", flush=True)
        else:
            print(msg)

    def progress_done(self) -> None:
        if not self.quiet and is_tty():
            print("")

    def box(self, label: str, value: str) -> None:
        if self.quiet:
            print(value)
            return
        print("")
        print(self._style(label, "1;36"))
        print(value)

    def output_box(self, label: str, value: str) -> None:
        if self.quiet:
            print(value)
            return
        print("")
        print(self._style("─" * 60, "90"))
        print(self._style(label, "1;32")) # Green for output
        print(value)
        print(self._style("─" * 60, "90"))
        print("")


class ConfigStore:
    SENSITIVE = {"app_id", "auth_token"}

    @staticmethod
    def load() -> Dict[str, Any]:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def save(data: Dict[str, Any]) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        safe = {k: v for k, v in data.items() if k not in ConfigStore.SENSITIVE}
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(safe, f, indent=2, sort_keys=True)
        os.replace(tmp, CONFIG_PATH)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass

    @classmethod
    def update(cls, **kwargs: Any) -> None:
        data = cls.load()
        data.update(kwargs)
        cls.save(data)

    @staticmethod
    def reset() -> None:
        try:
            os.remove(CONFIG_PATH)
        except FileNotFoundError:
            pass


class KeychainStore:
    @staticmethod
    def available() -> bool:
        return sys.platform == "darwin" and shutil.which("security") is not None

    @staticmethod
    def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["security", *args],
            capture_output=True,
            text=True,
            check=False,
        )

    @classmethod
    def get(cls, account: str) -> str:
        if not cls.available():
            return ""
        proc = cls._run(
            ["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"]
        )
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    @classmethod
    def set(cls, account: str, value: str) -> None:
        if not value or not cls.available():
            return
        proc = cls._run(
            ["add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value]
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(msg or "security command failed")

    @classmethod
    def delete(cls, account: str) -> None:
        if not cls.available():
            return
        cls._run(["delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account])


@dataclass(frozen=True)
class Auth:
    host: str
    app_id: str
    auth_token: str


class IconikClient:
    def __init__(self, auth: Auth, timeout_s: int = 30, retries: int = 4) -> None:
        self.auth = auth
        self.timeout_s = timeout_s
        self.retries = retries
        self._storage_map: Optional[Dict[str, Dict[str, Any]]] = None

    def _abs_url(self, path: str) -> str:
        host = self.auth.host.strip().rstrip("/") or "https://app.iconik.io"
        if not host.startswith(("http://", "https://")):
            host = "https://" + host
        if not path.startswith("/"):
            path = "/" + path
        return host + path

    def _request(self, method: str, path: str, json_data: Optional[dict] = None) -> Any:
        url = self._abs_url(path)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "App-ID": self.auth.app_id,
            "Auth-Token": self.auth.auth_token,
        }
        body = json.dumps(json_data).encode("utf-8") if json_data is not None else None
        last_err: Optional[BaseException] = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise PermissionError("Unauthorized. Check App-ID and Auth-Token.") from e
                if e.code == 403:
                    raise PermissionError(
                        "Forbidden. Check that your credentials have the required access permissions."
                    ) from e
                if e.code == 404:
                    raise FileNotFoundError(path) from e
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    sleep_s = retry_delay(e, attempt)
                    time.sleep(sleep_s)
                    last_err = e
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if attempt < self.retries - 1:
                    time.sleep(min(2 ** attempt, 20))
                    last_err = e
                    continue
                raise
        if last_err:
            raise RuntimeError(str(last_err))
        raise RuntimeError("Request failed.")

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, json_data: dict) -> Any:
        return self._request("POST", path, json_data)

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        try:
            data = self.get(f"/API/assets/v1/assets/{asset_id}/")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def list_share_assets(self, share_id: str) -> List[Dict[str, Any]]:
        try:
            data = self.get(f"/API/acls/v1/shares/{quote_path(share_id)}/assets/?page=1&per_page=100")
            assets = objects_from(data)
            total = int_or_zero(data.get("total") if isinstance(data, dict) else 0)
            if total > len(assets):
                next_url = data.get("next_url") if isinstance(data, dict) else None
                path = normalize_next_url(next_url, default_prefix=f"/API/acls/v1/shares/{quote_path(share_id)}/assets")
                while path:
                    data = self.get(path)
                    more = objects_from(data)
                    if not more:
                        break
                    assets.extend(more)
                    next_url = data.get("next_url") if isinstance(data, dict) else None
                    path = normalize_next_url(next_url, default_prefix=f"/API/acls/v1/shares/{quote_path(share_id)}/assets")
            return assets
        except FileNotFoundError:
            pass
        data = self.get(f"/API/acls/v1/shares/{quote_path(share_id)}/")
        if isinstance(data, dict):
            for key in ("asset_id", "object_id", "id"):
                value = data.get(key)
                if isinstance(value, str) and UUID_RE.match(value):
                    return [{"id": value}]
        return []

    def list_files(self, asset_id: str) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        path: Optional[str] = f"/API/files/v1/assets/{asset_id}/files/?page=1&per_page=100"
        while path:
            data = self.get(path)
            objects = objects_from(data)
            if not objects:
                break
            files.extend(objects)
            next_url = data.get("next_url") if isinstance(data, dict) else None
            path = normalize_next_url(next_url, default_prefix=f"/API/files/v1/assets/{asset_id}/files")
        return files

    def list_collection_contents(self, collection_id: str) -> Tuple[List[Dict[str, Any]], int]:
        data = self.get(f"/API/assets/v1/collections/{collection_id}/contents/?page=1&per_page=10")
        objects = objects_from(data)
        total = int_or_zero(data.get("total") if isinstance(data, dict) else 0)
        return objects, total

    def download_url(self, asset_id: str, file_id: str) -> Dict[str, Any]:
        data = self.get(
            f"/API/files/v1/assets/{asset_id}/files/{quote_path(file_id)}/download_url/"
        )
        return data if isinstance(data, dict) else {}

    def list_storages(self) -> List[Dict[str, Any]]:
        storages: List[Dict[str, Any]] = []
        path: Optional[str] = "/API/files/v1/storages/?page=1&per_page=200"
        while path:
            data = self.get(path)
            objects = objects_from(data)
            if not objects:
                break
            storages.extend(objects)
            next_url = data.get("next_url") if isinstance(data, dict) else None
            path = normalize_next_url(next_url, default_prefix="/API/files")
        return storages

    def storage_map(self) -> Dict[str, Dict[str, Any]]:
        if self._storage_map is None:
            storage_map: Dict[str, Dict[str, Any]] = {}
            try:
                for storage in self.list_storages():
                    storage_id = storage.get("id")
                    if not isinstance(storage_id, str):
                        continue
                    storage_map[storage_id] = {
                        "storage_name": storage.get("name") or "",
                        "storage_purpose": storage.get("purpose") or "",
                        "storage_method": storage.get("method") or storage.get("storage_method") or "",
                    }
            except Exception:
                storage_map = {}
            self._storage_map = storage_map
        return self._storage_map


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def normalize_next_url(next_url: Any, default_prefix: str) -> Optional[str]:
    if not isinstance(next_url, str) or not next_url.strip():
        return None
    value = next_url.strip()
    if value.startswith("/API/"):
        return value
    if value.startswith("/"):
        return default_prefix.rstrip("/") + value
    return default_prefix.rstrip("/") + "/" + value


def retry_delay(err: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = err.headers.get("Retry-After") if err.headers else None
    if retry_after and retry_after.isdigit():
        return float(min(int(retry_after), 60))
    return float(min(2 ** attempt, 20))


def objects_from(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("objects"), list):
        return [obj for obj in data["objects"] if isinstance(obj, dict)]
    if isinstance(data, list):
        return [obj for obj in data if isinstance(obj, dict)]
    return []


def normalize_mode(value: Optional[str], default: str, allowed: Sequence[str]) -> str:
    mode = (value or default).strip().upper()
    return mode if mode in allowed else default


def sanitize_path(path: str) -> str:
    p = (path or "").strip().strip('"').strip("'")
    if p.startswith("file://"):
        try:
            p = urllib.parse.urlparse(p).path
        except Exception:
            pass
    return os.path.abspath(os.path.expanduser(p.replace("\\ ", " ")))


def parse_target(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError("Empty input.")
    if s.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(s)
        path = parsed.path or ""
        m = COLLECTION_URL_RE.search(path)
        if m:
            return ("collection", m.group(1))
        m = ASSET_URL_RE.search(path)
        if m:
            return ("asset", m.group(1))
        m = SHORT_SHARE_RE.search(path) or SHARE_PATH_RE.search(path)
        if m:
            return ("share", m.group(1))
        m = ANY_UUID_RE.search(s)
        if m:
            return ("asset", m.group(1))
        raise ValueError("Unrecognized Iconik URL.")
    if S3_URI_RE.match(s):
        return ("reverse", s)
    if UUID_RE.match(s):
        return ("asset", s)
    return ("share", s)


def reverse_lookup(client: IconikClient, uri: str) -> Dict[str, Any]:
    m = S3_URI_RE.match(uri)
    if not m:
        raise ValueError("Invalid S3 URI format.")
    bucket, key = m.group(1), m.group(2)
    key = key.strip("/")

    # Try to scope search by storage_id if bucket maps to a known storage.
    storage_filter: List[Dict[str, Any]] = []
    try:
        smap = client.storage_map()
        matching_ids = [
            sid for sid, info in smap.items()
            if bucket.lower() in (info.get("storage_name") or "").lower()
        ]
        if matching_ids:
            storage_filter = [{"terms": {"files.storage_id": matching_ids}}]
    except Exception:
        pass  # Proceed without scoping — still useful.

    payload: Dict[str, Any] = {
        "query": f'files.path:"{key}"',
        "doc_types": ["assets"],
    }
    if storage_filter:
        payload["filter"] = {"bool": {"must": storage_filter}}
    res = client.post("/API/search/v1/search/", payload)

    objects = objects_from(res)
    if not objects:
        # Fallback: search by filename only (less precise).
        filename = key.split("/")[-1]
        if filename != key:
            payload["query"] = f'files.name:"{filename}"'
            res = client.post("/API/search/v1/search/", payload)
            objects = objects_from(res)

    return {
        "type": "reverse_list",
        "id": uri,
        "results": objects
    }


def choose_file(files: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    for fobj in files:
        value = str(fobj.get("is_original") or fobj.get("original") or "").lower()
        if value in ("true", "1", "yes"):
            return dict(fobj)
    if not files:
        raise RuntimeError("No files found on asset, or file access is missing.")
    return dict(sorted(files, key=lambda f: int_or_zero(f.get("size")), reverse=True)[0])


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def extract_urls(obj: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(obj, dict):
        for key in ("download_url", "url", "href"):
            value = obj.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                urls.append(value)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                urls.extend(extract_urls(value))
    elif isinstance(obj, list):
        for item in obj:
            urls.extend(extract_urls(item))
    seen = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def presigned_to_https(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def presigned_to_s3(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")
    m = re.match(r"^([^.]+)\.s3[.-][^.]+\.amazonaws\.com$", host)
    if m:
        return f"s3://{m.group(1)}/{path}"
    if re.match(r"^s3[.-][^.]+\.amazonaws\.com$", host) and "/" in path:
        bucket, key = path.split("/", 1)
        return f"s3://{bucket}/{key}"
    if any(token in host for token in (".wasabisys.com", ".backblazeb2.com", ".cloudflarestorage.com")) and "/" in path:
        bucket, key = path.split("/", 1)
        return f"s3://{bucket}/{key}"
    first = host.split(".")[0]
    if first and first.lower() not in ("s3", "storage", "objects") and path:
        return f"s3://{first}/{path}"
    return url


def format_url(url: str, mode: str) -> str:
    if mode == "FULL":
        return url
    if mode == "S3":
        return presigned_to_s3(url)
    return presigned_to_https(url)


def as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "online", "active"):
            return True
        if lowered in ("false", "0", "no", "offline", "missing", "deleted"):
            return False
    return None


def infer_online_status(fobj: Dict[str, Any], has_download_url: bool = False) -> Tuple[bool, str]:
    explicit = as_bool(fobj.get("is_online"))
    if explicit is not None:
        return explicit, "ONLINE" if explicit else "OFFLINE"

    for key in ("availability", "online_status", "storage_status"):
        value = fobj.get(key)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("online", "available", "active"):
                return True, "ONLINE"
            if lowered in ("offline", "missing", "unavailable", "deleted"):
                return False, "OFFLINE"

    status = str(fobj.get("status") or "").strip().upper()
    if status in ("DELETED", "MISSING", "OFFLINE", "UNAVAILABLE", "FAILED", "ERROR"):
        return False, "OFFLINE"

    # A successful download URL is the strongest signal this locator has.
    if has_download_url:
        return True, "ONLINE"

    # CLOSED is normal for Iconik file records, not an offline signal.
    if status in ("ACTIVE", "CLOSED", "READY", "FINISHED", "COMPLETE", "COMPLETED"):
        return True, "ONLINE"

    return True, "ONLINE"


def storage_metadata(client: IconikClient, fobj: Dict[str, Any]) -> Dict[str, str]:
    storage_id = fobj.get("storage_id") or fobj.get("storage") or ""
    storage_id = storage_id if isinstance(storage_id, str) else ""
    storage_method = str(fobj.get("storage_method") or "").strip()
    storage_name = str(fobj.get("storage_name") or "").strip()
    storage: Dict[str, Any] = {}
    if storage_id and not storage_name and storage_method.upper() not in ("", "S3"):
        storage = client.storage_map().get(storage_id, {})
    storage_name = str(
        storage_name
        or storage.get("storage_name")
        or storage.get("name")
        or ""
    ).strip()
    storage_method = str(
        storage_method
        or storage.get("storage_method")
        or storage.get("method")
        or ""
    ).strip()
    return {
        "storage_id": storage_id,
        "storage_name": storage_name,
        "storage_method": storage_method,
    }


def join_storage_path(*parts: str) -> str:
    clean = []
    for part in parts:
        text = str(part or "").strip().strip("/")
        if text:
            clean.append(text)
    return "/".join(clean)


def path_from_file_metadata(client: IconikClient, fobj: Dict[str, Any]) -> str:
    for key in ("file_path", "filepath", "path", "absolute_path", "local_path"):
        value = fobj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    directory = fobj.get("directory_path") or fobj.get("directory") or fobj.get("folder_path") or ""
    directory = directory if isinstance(directory, str) else ""
    file_name = fobj.get("filename") or fobj.get("name") or fobj.get("original_name") or ""
    file_name = file_name if isinstance(file_name, str) else ""
    meta = storage_metadata(client, fobj)
    storage_label = meta["storage_name"] or meta["storage_method"]
    return join_storage_path(storage_label, directory, file_name)


def make_location(
    uri: str,
    fobj: Dict[str, Any],
    client: IconikClient,
    source: str,
    has_download_url: bool,
) -> Dict[str, Any]:
    is_online, status = infer_online_status(fobj, has_download_url=has_download_url)
    meta = storage_metadata(client, fobj)
    return {
        "uri": uri,
        "is_online": is_online,
        "status": status,
        "source": source,
        "file_id": fobj.get("id") or fobj.get("file_id") or "",
        "file_name": fobj.get("filename") or fobj.get("name") or fobj.get("original_name") or "",
        "file_status": fobj.get("status") or "",
        **meta,
    }


def location_lines(locations: Sequence[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for loc in locations:
        status = str(loc.get("status") or ("ONLINE" if loc.get("is_online") else "OFFLINE"))
        uri = str(loc.get("uri") or "")
        
        method = str(loc.get("storage_method") or "").upper()
        purpose = str(loc.get("storage_purpose") or "").upper()
        storage_name = str(loc.get("storage_name") or "").upper()
        
        storage_type = "Unknown Storage"
        if method == "ISG":
            storage_type = "Local Server"
        elif method == "S3":
            storage_type = "AWS S3"
        elif "LUCID" in storage_name or "LUCID" in purpose or "LUCID" in method:
            storage_type = "LucidLink"
            
        storage_info = str(loc.get("storage_name") or loc.get("storage_method") or "").strip()
        suffix = f" ({storage_type}: {storage_info})" if storage_info else f" ({storage_type})"
        lines.append(f"[{status}]{suffix} {uri}".rstrip())
    return lines


def online_paths_from_locations(locations: Sequence[Dict[str, Any]], file_multi: str) -> List[str]:
    paths: List[str] = []
    seen = set()
    for loc in locations:
        if not loc.get("is_online", True):
            continue
        uri = str(loc.get("uri") or "")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        paths.append(uri)
    if file_multi == "FIRST" and paths:
        return paths[:1]
    return paths


def file_identity(fobj: Dict[str, Any]) -> Tuple[str, Any, str]:
    name = str(fobj.get("filename") or fobj.get("name") or "").strip()
    size = fobj.get("size")
    checksum = str(fobj.get("checksum") or fobj.get("md5") or fobj.get("sha1") or "").strip()
    return name, size, checksum


def replica_candidates(files: Sequence[Dict[str, Any]], chosen: Dict[str, Any]) -> List[Dict[str, Any]]:
    chosen_id = chosen.get("id") or chosen.get("file_id")
    chosen_name, chosen_size, chosen_checksum = file_identity(chosen)
    matches: List[Dict[str, Any]] = []
    for fobj in files:
        if (fobj.get("id") or fobj.get("file_id")) == chosen_id:
            continue
        name, size, checksum = file_identity(fobj)
        same_checksum = checksum and chosen_checksum and checksum == chosen_checksum
        same_name_size = name and chosen_name and name == chosen_name and size == chosen_size and size not in (None, 0, "0")
        if same_checksum or same_name_size:
            matches.append(dict(fobj))
    return matches


def resolve_storage_locations(
    client: IconikClient,
    asset_id: str,
    files: Sequence[Dict[str, Any]],
    chosen: Dict[str, Any],
    output_mode: str,
    file_multi: str,
) -> List[Dict[str, Any]]:
    all_files = [dict(chosen), *replica_candidates(files, chosen)[:10]]
    locations: List[Dict[str, Any]] = []
    seen = set()
    for fobj in all_files:
        file_id = fobj.get("id") or fobj.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            continue

        download_urls: List[str] = []
        try:
            download_urls = extract_urls(client.download_url(asset_id, file_id))
        except Exception:
            if fobj is chosen and not path_from_file_metadata(client, fobj):
                raise

        for url in download_urls:
            formatted = format_url(url, output_mode)
            if formatted in seen:
                continue
            seen.add(formatted)
            locations.append(
                make_location(
                    formatted,
                    fobj,
                    client,
                    source="download_url",
                    has_download_url=True,
                )
            )

        storage_method = str(fobj.get("storage_method") or "").strip().upper()
        should_check_metadata_path = not download_urls or storage_method not in ("", "S3")
        metadata_path = path_from_file_metadata(client, fobj) if should_check_metadata_path else ""
        should_add_metadata_path = bool(metadata_path)
        if should_add_metadata_path and metadata_path not in seen:
            seen.add(metadata_path)
            locations.append(
                make_location(
                    metadata_path,
                    fobj,
                    client,
                    source="file_metadata",
                    has_download_url=bool(download_urls),
                )
            )

    if not locations:
        raise RuntimeError("No storage location was returned for the selected file.")
    online_count = len(online_paths_from_locations(locations, "ALL"))
    if file_multi == "ERROR" and online_count > 1:
        raise RuntimeError("Multiple storage locations found. Use --multi-files FIRST or ALL.")
    return locations


def share_asset_ids(client: IconikClient, share_id: str, share_multi: str) -> Tuple[str, List[str]]:
    assets = client.list_share_assets(share_id)
    ids: List[str] = []
    for asset in assets:
        aid = asset.get("id") or asset.get("asset_id") or asset.get("object_id")
        if isinstance(aid, str) and UUID_RE.match(aid) and aid not in ids:
            ids.append(aid)
    if not ids:
        return ("NONE", [])
    if len(ids) == 1:
        return ("OK", ids)
    if share_multi == "ERROR":
        return ("MULTI", ids)
    if share_multi == "FIRST":
        return ("OK", ids[:1])
    return ("OK_ALL", ids)


def resolve_asset(
    client: IconikClient,
    asset_id: str,
    output_mode: str,
    file_multi: str,
) -> Dict[str, Any]:
    files = client.list_files(asset_id)
    chosen = choose_file(files)
    locations = resolve_storage_locations(client, asset_id, files, chosen, output_mode, file_multi)
    paths = online_paths_from_locations(locations, file_multi)
    meta = client.get_asset(asset_id)
    return {
        "asset_id": asset_id,
        "asset_title": meta.get("title") or meta.get("name") or "",
        "file_name": chosen.get("filename") or chosen.get("name") or "",
        "locations": locations,
        "paths": paths,
    }


def resolve_input(
    client: IconikClient,
    raw: str,
    output_mode: str,
    share_multi: str,
    file_multi: str,
) -> Dict[str, Any]:
    target_type, target_id = parse_target(raw)
    
    if target_type == "collection":
        objects, total = client.list_collection_contents(target_id)
        return {
            "type": "collection",
            "id": target_id,
            "total": total,
            "objects": objects[:3]
        }
        
    if target_type == "reverse":
        return reverse_lookup(client, raw)
        
    asset_ids: List[str]
    if target_type == "asset":
        asset_ids = [target_id]
    else:
        status, ids = share_asset_ids(client, target_id, share_multi)
        if status == "NONE":
            raise RuntimeError("Share does not resolve to an accessible asset.")
        if status == "MULTI":
            raise RuntimeError(f"Share resolves to {len(ids)} assets. Use --multi FIRST or ALL.")
        asset_ids = ids
        
    return {
        "type": "asset_list",
        "id": target_id,
        "results": [resolve_asset(client, aid, output_mode, file_multi) for aid in asset_ids]
    }


def all_paths(results: Sequence[Dict[str, Any]]) -> List[str]:
    paths: List[str] = []
    for result in results:
        for path in result.get("paths") or []:
            paths.append(str(path))
    return paths


def print_lookup(
    ui: UI,
    results: Sequence[Dict[str, Any]],
    as_json: bool,
    uri_only: bool,
) -> None:
    if as_json:
        print(json.dumps({"version": VERSION, "assets": list(results)}, ensure_ascii=False, indent=2))
        return
    paths = all_paths(results)
    if uri_only:
        print("\n".join(paths))
        return
    locations = []
    for result in results:
        locations.extend(result.get("locations") or [])
    if locations:
        label = "Located URI" if len(locations) == 1 else "Located URIs"
        ui.box(label, "\n".join(location_lines(locations)))
    elif paths:
        label = "Located URI" if len(paths) == 1 else "Located URIs"
        ui.box(label, "\n".join(paths))
    if len(results) > 1:
        ui.box("Assets", str(len(results)))
    for idx, result in enumerate(results, 1):
        prefix = f"Asset {idx}" if len(results) > 1 else "Asset"
        ui.box(prefix, f"{result.get('asset_title') or '(untitled)'}\n{result.get('asset_id')}")
        ui.box("Selected file", str(result.get("file_name") or "(unnamed)"))
        result_paths = result.get("paths") or []
        if result_paths:
            label = "Output" if len(result_paths) == 1 else f"Outputs ({len(result_paths)})"
            ui.output_box(label, "\n".join(str(p) for p in result_paths))
        else:
            ui.output_box("Outputs (0)", "No online storage locations found.")


def copy_to_clipboard(value: str) -> bool:
    if sys.platform != "darwin" or not shutil.which("pbcopy"):
        return False
    proc = subprocess.run(["pbcopy"], input=value, text=True, check=False)
    return proc.returncode == 0




def load_settings(args: argparse.Namespace, ui: UI) -> Tuple[str, str, str, str, str, str]:
    cfg = ConfigStore.load()
    legacy_app = cfg.get("app_id") if isinstance(cfg.get("app_id"), str) else ""
    legacy_token = cfg.get("auth_token") if isinstance(cfg.get("auth_token"), str) else ""

    host = args.host or cfg.get("host") or "https://app.iconik.io"
    saved_output = cfg.get("output") if cfg.get("config_version") == VERSION else None
    output_mode = normalize_mode(args.output or saved_output, "S3", VALID_OUTPUTS)
    share_multi = normalize_mode(args.multi or cfg.get("multi_share") or cfg.get("multi"), "ERROR", VALID_MULTI)
    file_multi = normalize_mode(args.multi_files or cfg.get("file_multi"), "ALL", VALID_MULTI)
    app_id = args.app_id or KeychainStore.get(KEYCHAIN_ACCOUNT_APP_ID) or legacy_app
    auth_token = args.auth_token or KeychainStore.get(KEYCHAIN_ACCOUNT_AUTH_TOKEN) or legacy_token

    if not app_id:
        app_id = ui.ask("App-ID")
    if not auth_token:
        auth_token = ui.secret("Auth-Token")
    if not app_id or not auth_token:
        raise RuntimeError("App-ID and Auth-Token are required.")

    should_save = not args.no_save
    if should_save:
        ConfigStore.update(
            host=host.rstrip("/"),
            config_version=VERSION,
            output=output_mode,
            multi_share=share_multi,
            multi=share_multi,
            file_multi=file_multi,
            multi_prefs_initialized=True,
        )
        try:
            KeychainStore.set(KEYCHAIN_ACCOUNT_APP_ID, app_id)
            KeychainStore.set(KEYCHAIN_ACCOUNT_AUTH_TOKEN, auth_token)
        except Exception as exc:
            ui.warn(f"Could not save credentials to Keychain: {exc}")

    return host, app_id, auth_token, output_mode, share_multi, file_multi


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="iconik_locator",
        description="Quickly locate the S3 URI, or best fallback URL, for Iconik assets.",
    )
    p.add_argument("target", nargs="?", help="Asset URL, share URL, asset UUID, or collection URL.")
    p.add_argument("--input", "-i", dest="input", help="Asset/share/UUID or collection URL.")
    p.add_argument("--host", help="Iconik host. Default: https://app.iconik.io")
    p.add_argument("--app-id", help="Iconik App-ID. Saved to Keychain unless --no-save is used.")
    p.add_argument("--auth-token", help="Iconik Auth-Token. Saved to Keychain unless --no-save is used.")
    p.add_argument("--output", choices=VALID_OUTPUTS, help="Storage path output format. Default: S3.")
    p.add_argument("--multi", choices=VALID_MULTI, help="Multi-asset share behavior.")
    p.add_argument("--multi-files", choices=VALID_MULTI, help="Multi-source file behavior.")
    p.add_argument("--json", action="store_true", help="Print single lookup result as JSON.")
    p.add_argument("--uri-only", action="store_true", help="Print only located URI values, one per line.")
    p.add_argument("--copy", action="store_true", help="Copy first resolved path to clipboard on macOS.")
    p.add_argument("--no-save", action="store_true", help="Do not save config or credentials.")
    p.add_argument("--quiet", action="store_true", help="Reduce non-result output.")
    p.add_argument("--reset", action="store_true", help="Remove saved config and Keychain credentials, then exit.")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    return p


def interactive_loop(ui: UI, client: IconikClient, output_mode: str, share_multi: str, file_multi: str, args: argparse.Namespace) -> None:
    ui.note(f"Host: {client.auth.host}  Output: {output_mode}  Share multi: {share_multi}  File multi: {file_multi}")
    ui.info("Welcome to the Iconik Locator interactive mode. Type 'help' at any time for instructions.")
    while True:
        raw = ui.ask("Paste an Iconik link, S3 URI, or asset UUID (q=quit)")
        
        # Check for quit
        if raw.lower() in ("q", "quit", "exit", "no", "n"):
            return
            
        # Check for help
        if raw.lower() == "help":
            ui.info("Help: Bidirectional lookup between Iconik and cloud storage.")
            ui.info("Supported inputs:")
            ui.info("  - Asset URL (e.g. https://app.iconik.io/asset/...)")
            ui.info("  - Share URL (e.g. https://app.iconik.io/share/...)")
            ui.info("  - Asset UUID")
            ui.info("  - Collection URL (displays first 3 items)")
            ui.info("  - S3 URI for reverse lookup (e.g. s3://bucket/path/to/file.mov)")
            continue

        ui.progress("Looking up...")
        try:
            run_target(ui, client, raw, output_mode, share_multi, file_multi, args)
        except KeyboardInterrupt:
            ui.progress_done()
            raise
        except PermissionError as exc:
            ui.err(str(exc))
        except FileNotFoundError:
            ui.err("Object not found. Check the link/ID and your access.")
        except urllib.error.URLError as exc:
            ui.err(f"Network error: {exc}")
        except Exception as exc:
            ui.err(f"Unexpected error: {exc}")
        finally:
            ui.progress_done()


def run_target(
    ui: UI,
    client: IconikClient,
    target: str,
    output_mode: str,
    share_multi: str,
    file_multi: str,
    args: argparse.Namespace,
) -> None:
    clean = sanitize_path(target) if os.path.exists(os.path.expanduser(target.strip().strip('"').strip("'"))) else target
    result_data = resolve_input(client, clean, output_mode, share_multi, file_multi)
    
    if result_data["type"] == "collection":
        objects = result_data["objects"]
        total = result_data["total"]
        ui.warn(f"Collection detected with {total} total items.")
        ui.info("Note: This tool is intended for single-asset lookup. Here are the first 3 items:")
        for obj in objects:
            obj_type = str(obj.get("object_type", "Unknown")).capitalize()
            obj_title = str(obj.get("title", "Untitled"))
            ui.info(f"  - {obj_type}: {obj_title}")
        if total > 3:
            ui.info(f"  ... and {total - 3} more items.")
        return
        
    if result_data["type"] == "reverse_list":
        objects = result_data["results"]
        if not objects:
            ui.output_box("Outputs (0)", "No Iconik assets found matching that storage path.")
            return
        ui.box("Located Iconik Assets", str(len(objects)))
        first_url = ""
        for idx, obj in enumerate(objects, 1):
            asset_id = obj.get("id")
            title = obj.get("title") or "(untitled)"
            url = f"{client.auth.host.rstrip('/')}/asset/{asset_id}"
            if not first_url:
                first_url = url
            prefix = f"Asset {idx}" if len(objects) > 1 else "Asset"
            ui.box(prefix, f"{title}\n{asset_id}")
            ui.output_box("Iconik URL", url)
        if args.copy and first_url:
            if copy_to_clipboard(first_url):
                ui.note("Copied first Iconik URL to clipboard.")
            else:
                ui.warn("Could not copy to clipboard.")
        return
        
    results = result_data["results"]
    print_lookup(ui, results, args.json, args.uri_only)
    if args.copy and results and results[0].get("paths"):
        if copy_to_clipboard(str(results[0]["paths"][0])):
            ui.note("Copied first path to clipboard.")
        else:
            ui.warn("Could not copy to clipboard.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.quiet and not args.json:
        args.uri_only = True
    ui = UI(quiet=args.quiet)

    if args.version:
        print(VERSION)
        return 0

    if args.reset:
        ConfigStore.reset()
        KeychainStore.delete(KEYCHAIN_ACCOUNT_APP_ID)
        KeychainStore.delete(KEYCHAIN_ACCOUNT_AUTH_TOKEN)
        ui.info("Saved config and Keychain credentials removed.")
        return 0

    ui.banner()
    try:
        host, app_id, auth_token, output_mode, share_multi, file_multi = load_settings(args, ui)
        client = IconikClient(Auth(host=host, app_id=app_id, auth_token=auth_token))
        target = args.input or args.target
        if target:
            ui.progress("Looking up...")
            run_target(ui, client, target, output_mode, share_multi, file_multi, args)
            ui.progress_done()
        else:
            interactive_loop(ui, client, output_mode, share_multi, file_multi, args)
        return 0
    except KeyboardInterrupt:
        ui.progress_done()
        ui.err("Interrupted.")
        return 130
    except PermissionError as exc:
        ui.progress_done()
        ui.err(str(exc))
        return 3
    except FileNotFoundError:
        ui.progress_done()
        ui.err("Object not found. Check the link/ID and your access.")
        return 4
    except Exception as exc:
        ui.progress_done()
        ui.err(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

