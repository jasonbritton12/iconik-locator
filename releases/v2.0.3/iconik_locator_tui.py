#!/usr/bin/env python3
# iconik_locator_tui v2_0_3
#
# - First-run preferences:
#     * Multi-asset share links (ERROR | FIRST | ALL)
#     * Multi-source file storage (ERROR | FIRST | ALL)
# - Interactive updates at the prompt:
#     * --multi ERROR|FIRST|ALL
#     * --multi-files ERROR|FIRST|ALL
#       (can be used alone, or before a URL/UUID/CSV/XLSX in the same line)
# - Friendlier UX:
#     * Welcome banner text
#     * Clear column & output path confirmations
#     * "Would you like to look up another?" wording
# - Batch UX:
#     * Rich table preview
#     * Auto-detect link/ID column
#     * Single confirmation prompt: "Which column contains the links or IDs…"
# - Robust CSV/XLSX handling with openpyxl for Excel, CSV fallback
# - Multi-source file preference:
#     * ERROR – error if multiple storage locations for a file
#     * FIRST – use the first storage location only
#     * ALL – return all locations (default)
# - Multi-asset share preference:
#     * ERROR – error if share resolves to >1 asset
#     * FIRST – use first asset
#     * ALL – expand to many

from __future__ import annotations

import os
import re
import sys
import json
import time
import platform
import subprocess
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

VERSION = "v2_0_3"

# ============================================================
# Dependency helpers
# ============================================================

def ensure_package_interactive(
    pip_names: List[str],
    import_name: str,
    why: str,
    cancel_ok: bool = True,
) -> bool:
    """
    Best-effort, interactive installer for optional deps.
    Returns True if the package is importable after this call.
    """
    try:
        __import__(import_name)
        return True
    except Exception:
        pass

    print(f"\nThe '{import_name}' package is required {why}.")
    while True:
        yn = input(f"Install {', '.join(pip_names)} now? [Y/n]: ").strip().lower()
        if yn in ("", "y", "yes"):
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", *pip_names])
                __import__(import_name)
                return True
            except Exception as e:
                print(f"Installation failed: {e}", file=sys.stderr)
                if cancel_ok:
                    again = input("Try again? [Y/n]: ").strip().lower()
                    if again in ("n", "no"):
                        sure = input(
                            "Are you sure? Proceeding will skip this feature. [y/N]: "
                        ).strip().lower()
                        if sure in ("y", "yes"):
                            return False
        elif yn in ("n", "no"):
            if cancel_ok:
                sure = input(
                    "Are you sure? Proceeding will skip this feature. [y/N]: "
                ).strip().lower()
                if sure in ("y", "yes"):
                    return False
        # anything else → re-ask


# Hard requirement: requests
try:
    import requests  # type: ignore
except Exception:
    ok = ensure_package_interactive(
        ["requests"], "requests", "to contact the iconik API", cancel_ok=False
    )
    if not ok:
        print("Cannot continue without 'requests'.", file=sys.stderr)
        sys.exit(2)
    import requests  # type: ignore

# Optional: rich
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.theme import Theme
    from rich.table import Table
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn

    RICH = True
except Exception:
    RICH = False
    Console = Panel = Text = Theme = Table = Progress = None  # type: ignore

# Optional: pandas (for CSV/XLSX)
try:
    import pandas as pd  # type: ignore

    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False
    pd = None  # type: ignore


# ============================================================
# Theme & UI
# ============================================================

class ThemeConfig:
    primary = "#00e09f"
    primary_dim = "#008c76"
    accent = "#00bcd4"
    warn = "bold yellow"
    error = "bold red"
    bg = "#000000"
    fg = "#cfeee6"

    @staticmethod
    def rich_theme() -> Theme:
        return Theme(
            {
                "app.title": f"bold {ThemeConfig.primary} on {ThemeConfig.bg}",
                "app.text": f"{ThemeConfig.fg} on {ThemeConfig.bg}",
                "app.dim": f"{ThemeConfig.primary_dim} on {ThemeConfig.bg}",
                "app.box": f"{ThemeConfig.primary} on {ThemeConfig.bg}",
                "app.err": f"{ThemeConfig.error} on {ThemeConfig.bg}",
                "app.warn": f"{ThemeConfig.warn} on {ThemeConfig.bg}",
            }
        )


class UI:
    def __init__(self, force_terminal: bool = True):
        self.rich = RICH
        if self.rich:
            self.console = Console(
                force_terminal=force_terminal, theme=ThemeConfig.rich_theme()
            )
        else:
            self.console = None

    def banner(self, title: str):
        if self.rich:
            self.console.print(
                Panel(
                    Text(f" {title} ", style="app.title"),
                    border_style="app.box",
                )
            )
        else:
            print(f"=== {title} ===")

    def info(self, msg: str):
        if self.rich:
            self.console.print(Text(msg, style="app.text"))
        else:
            print(msg)

    def note(self, msg: str):
        if self.rich:
            self.console.print(Text(msg, style="app.dim"))
        else:
            print(msg)

    def warn(self, msg: str):
        if self.rich:
            self.console.print(Text(msg, style="app.warn"))
        else:
            print(f"WARNING: {msg}")

    def err(self, msg: str):
        if self.rich:
            self.console.print(Text(msg, style="app.err"))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)

    def box(self, label: str, value: str):
        if self.rich:
            self.console.print(
                Panel(
                    Text(value, style="app.text"),
                    title=label,
                    border_style="app.box",
                    style="on " + ThemeConfig.bg,
                )
            )
        else:
            print(f"\n{label}:\n{value}\n")

    def ask(self, prompt: str, default: Optional[str] = None) -> str:
        if self.rich:
            label = Text(prompt, style="app.text")
            if default is not None and default != "":
                label.append(f" [{default}]")
            label.append(": ")
            resp = self.console.input(label)
            return (resp.strip() or (default or "")).strip()
        else:
            raw = input(f"{prompt}{' ['+default+']' if default else ''}: ")
            return raw.strip() or (default or "")

    def confirm(self, prompt: str, default: bool = True) -> bool:
        if self.rich:
            yn = "Y/n" if default else "y/N"
            label = Text(f"{prompt} [{yn}]: ", style="app.text")
            resp = self.console.input(label).strip().lower()
            if resp == "":
                return default
            return resp in ("y", "yes")
        else:
            raw = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
            return (raw == "" and default) or raw in ("y", "yes")

    def progress(self):
        if self.rich and Progress:
            return Progress(
                TextColumn("[app.dim]{task.description}"),
                BarColumn(bar_width=30, style="app.box"),
                TextColumn("[app.text]{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=self.console,
                transient=True,
            )
        else:
            return None

    def table_preview(self, df, max_rows: int = 6):
        if not self.rich or Table is None:
            try:
                self.info(df.head(max_rows).to_string(max_cols=10, max_rows=max_rows))
            except Exception:
                self.info(str(df.head(max_rows)))
            return

        t = Table(show_lines=False, header_style="app.box", row_styles=["app.text"])
        cols = list(map(str, df.columns))
        t.add_column("#", style="app.dim", width=4)
        for c in cols:
            t.add_column(str(c))
        try:
            head = df.head(max_rows)
            for idx, (_, row) in enumerate(head.iterrows()):
                values = [str(row.get(c, "")) for c in cols]
                t.add_row(str(idx), *values)
        except Exception:
            pass
        self.console.print(t)


# ============================================================
# Config store
# ============================================================

class ConfigStore:
    @staticmethod
    def config_dir() -> str:
        home = os.path.expanduser("~")
        sysname = platform.system().lower()
        if "darwin" in sysname or "mac" in sysname:
            return os.path.join(home, "Library", "Application Support", "IconikLocator")
        elif "windows" in sysname:
            base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
            return os.path.join(base, "IconikLocator")
        else:
            return os.path.join(home, ".config", "iconik-locator")

    @classmethod
    def file_path(cls) -> str:
        return os.path.join(cls.config_dir(), "config.json")

    @classmethod
    def read_all(cls) -> Dict[str, Any]:
        try:
            with open(cls.file_path(), "r") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    @classmethod
    def write_all(cls, data: Dict[str, Any]):
        os.makedirs(cls.config_dir(), exist_ok=True)
        tmp = cls.file_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, cls.file_path())
        if os.name == "posix":
            os.chmod(cls.file_path(), 0o600)

    @classmethod
    def load(
        cls,
    ) -> Tuple[str, str, str, str, Optional[str], Optional[str], bool]:
        d = cls.read_all()
        host = (d.get("host") or "https://app.iconik.io").rstrip("/")
        output = (d.get("output") or "HTTPS").upper()
        # Backwards compatibility: "multi" was share handling in earlier versions
        share_multi = d.get("multi_share") or d.get("multi")
        file_multi = d.get("file_multi")
        prefs_init = bool(d.get("multi_prefs_initialized", False))
        return (
            d.get("app_id", ""),
            d.get("auth_token", ""),
            host,
            output,
            share_multi,
            file_multi,
            prefs_init,
        )

    @classmethod
    def set(cls, **kwargs):
        d = cls.read_all()
        d.update(kwargs)
        cls.write_all(d)

    @classmethod
    def get_flag(cls, key: str, default=None):
        return cls.read_all().get(key, default)

    @classmethod
    def set_flag(cls, key: str, value):
        d = cls.read_all()
        d[key] = value
        cls.write_all(d)

    @classmethod
    def reset(cls) -> bool:
        try:
            if os.path.exists(cls.file_path()):
                os.remove(cls.file_path())
                return True
        except Exception:
            pass
        return False


# ============================================================
# Input helpers
# ============================================================

class InputHelpers:
    @staticmethod
    def masked_input(prompt: str) -> str:
        """
        Masked input with asterisks, but still handles backspace and ignores arrows.
        Falls back to getpass/input if termios is unavailable.
        """
        try:
            import termios
            import tty
            import select  # type: ignore

            sys.stdout.write(prompt)
            sys.stdout.flush()
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                buf: List[str] = []
                while True:
                    ch = sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        return "".join(buf)
                    if ch == "\x03":
                        raise KeyboardInterrupt
                    if ch in ("\x7f", "\b", "\x08"):
                        if buf:
                            buf.pop()
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                        continue
                    if ch == "\x1b":
                        # swallow escape sequences (arrows, etc.)
                        import select as sel

                        while True:
                            r, _, _ = sel.select([sys.stdin], [], [], 0.01)
                            if not r:
                                break
                            _ = sys.stdin.read(1)
                        continue
                    if ord(ch) < 32:
                        continue
                    buf.append(ch)
                    sys.stdout.write("*")
                    sys.stdout.flush()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            try:
                import getpass

                return getpass.getpass(prompt)
            except Exception:
                return input(prompt)

    @staticmethod
    def sanitize_path(p: str) -> str:
        p = (p or "").strip().strip('"').strip("'")
        if p.startswith("file://"):
            try:
                p = urllib.parse.urlparse(p).path
            except Exception:
                pass
        p = p.replace("\\ ", " ")
        p = os.path.expanduser(p)
        return p

    @staticmethod
    def is_list_file(p: str) -> bool:
        p = InputHelpers.sanitize_path(p)
        return (
            os.path.exists(p)
            and os.path.isfile(p)
            and os.path.splitext(p)[1].lower() in (".csv", ".tsv", ".xlsx", ".xls")
        )


# ============================================================
# Iconik client
# ============================================================

class IconikClient:
    def __init__(self, host: str, app_id: str, auth_token: str, timeout: int = 30):
        self.host = host.rstrip("/")
        self.sess = requests.Session()
        self.sess.headers.update(
            {
                "Content-Type": "application/json",
                "App-ID": app_id,
                "Auth-Token": auth_token,
            }
        )
        self.timeout = timeout

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        backoff = 0.8
        for attempt in range(4):
            r = self.sess.get(url, timeout=self.timeout)
            code = r.status_code
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(backoff)
                backoff *= 1.8
                continue
            if code == 401:
                raise PermissionError("Unauthorized (check App-ID/Auth-Token).")
            if code == 403:
                raise PermissionError(
                    "Forbidden (missing permissions; ask an admin to grant access / original downloads)."
                )
            if code == 404:
                raise FileNotFoundError(path)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                raise RuntimeError(f"Non-JSON response from {path}")

    def list_share_assets(self, share_id: str) -> List[Dict[str, Any]]:
        try:
            data = self._get(f"/API/acls/v1/shares/{share_id}/assets/")
            if isinstance(data, dict) and "objects" in data:
                return data["objects"] or []
            if isinstance(data, list):
                return data
        except FileNotFoundError:
            pass

        share = self._get(f"/API/acls/v1/shares/{share_id}/")
        items: List[Dict[str, Any]] = []
        if isinstance(share, dict):
            for k in ("asset_id", "object_id", "id"):
                v = share.get(k)
                if isinstance(v, str) and re.match(r"^[0-9a-f-]{36}$", v, re.I):
                    items.append({"id": v})
                    break
        return items

    def list_files(self, asset_id: str) -> List[Dict[str, Any]]:
        data = self._get(f"/API/files/v1/assets/{asset_id}/files/")
        if isinstance(data, dict) and "objects" in data:
            return data["objects"] or []
        if isinstance(data, list):
            return data
        return []

    def get_download_url(self, asset_id: str, file_id: str) -> Dict[str, Any]:
        return self._get(f"/API/files/v1/assets/{asset_id}/files/{file_id}/download_url/")

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        try:
            return self._get(f"/API/assets/v1/assets/{asset_id}/")
        except Exception:
            return {}


# ============================================================
# Parsing & formatting
# ============================================================

ASSET_URL_RE = re.compile(
    r"https?://[^/]+/asset/([0-9a-f-]{36})(?:/)?(?:[?#].*)?$", re.I
)
SHARE_URL_RE = re.compile(
    r"https?://(?:icnk\.io|.*iconik.*)/u/([A-Za-z0-9_-]+)(?:/)?(?:[?#].*)?$", re.I
)
UUID_RE = re.compile(r"^[0-9a-f-]{36}$", re.I)
COLLECTION_URL_RE = re.compile(
    r"https?://[^/]+/collection/([0-9a-f-]{36})(?:[?#].*)?$", re.I
)


class Resolver:
    @staticmethod
    def parse_target(s: str) -> Tuple[str, str]:
        s = (s or "").strip().strip('"').strip("'")
        m = ASSET_URL_RE.match(s)
        if m:
            return ("asset_id", m.group(1))
        m = SHARE_URL_RE.match(s)
        if m:
            return ("share_id", m.group(1))
        m = UUID_RE.match(s)
        if m:
            return ("asset_id", s)
        m = COLLECTION_URL_RE.match(s)
        if m:
            return ("collection_url", s)
        # Fallback: treat it as share-like
        return ("share_id", s)

    @staticmethod
    def choose_file(files: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Prefer flagged "original" file
        for f in files:
            if str(f.get("is_original") or f.get("original") or "").lower() in (
                "true",
                "1",
            ):
                return f
        files_sorted = sorted(files, key=lambda f: f.get("size") or 0, reverse=True)
        if not files_sorted:
            raise RuntimeError(
                "No files on asset or insufficient permissions to view files."
            )
        return files_sorted[0]


class Formatter:
    @staticmethod
    def presigned_to_https(url: str) -> str:
        u = urllib.parse.urlparse(url)
        return f"{u.scheme}://{u.netloc}{u.path}"

    @staticmethod
    def presigned_to_s3(url: str) -> str:
        u = urllib.parse.urlparse(url)
        host, path = u.netloc, u.path.lstrip("/")

        m = re.match(r"^([^.]+)\.s3[.-][^/]+\.amazonaws\.com$", host)
        if m:
            return f"s3://{m.group(1)}/{path}"

        m = re.match(r"^s3[.-][^/]+\.amazonaws\.com$", host)
        if m and "/" in path:
            b, k = path.split("/", 1)
            return f"s3://{b}/{k}"

        if any(
            x in host
            for x in (".wasabisys.com", ".backblazeb2.com", ".cloudflarestorage.com")
        ) and "/" in path:
            b, k = path.split("/", 1)
            return f"s3://{b}/{k}"

        first = host.split(".")[0]
        if first and first.lower() not in ("s3", "storage", "objects") and path:
            return f"s3://{first}/{path}"

        return url

    @staticmethod
    def format(presigned: str, mode: str) -> str:
        m = (mode or "HTTPS").upper()
        if m == "FULL":
            return presigned
        if m == "S3":
            return Formatter.presigned_to_s3(presigned)
        return Formatter.presigned_to_https(presigned)


def extract_all_urls_from_response(resp: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    if not isinstance(resp, dict):
        return urls

    for k in ("download_url", "url", "href"):
        v = resp.get(k)
        if isinstance(v, str):
            urls.append(v)

    for k in ("download_urls", "urls", "links"):
        v = resp.get(k)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict):
                    for kk in ("download_url", "url", "href"):
                        vv = item.get(kk)
                        if isinstance(vv, str):
                            urls.append(vv)

    for wrap in ("object", "data", "result"):
        sub = resp.get(wrap)
        if isinstance(sub, dict):
            urls.extend(extract_all_urls_from_response(sub))
        elif isinstance(sub, list):
            for obj in sub:
                if isinstance(obj, dict):
                    urls.extend(extract_all_urls_from_response(obj))

    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def format_multi_for_cell(paths: List[str]) -> str:
    return "\n".join(paths)


def describe_share_multi(mode: str) -> str:
    m = mode.upper()
    if m == "FIRST":
        return "resolve the first asset in the share"
    if m == "ALL":
        return "resolve all assets in the share"
    return "show an error and ask for a single asset"


def describe_file_multi(mode: str) -> str:
    m = mode.upper()
    if m == "FIRST":
        return "use the first storage location for each file"
    if m == "ALL":
        return "return all storage locations for each file"
    return "show an error if multiple storage locations are found"


# ============================================================
# Multi handling helpers
# ============================================================

def handle_assets_for_share(
    client: IconikClient, share_id: str, multi_mode: str
) -> Tuple[str, List[str]]:
    """
    Returns (status, asset_ids)
        status:
          "NONE"  → no assets resolved
          "MULTI" → multiple assets, but multi_mode=ERROR
          "OK"    → single asset (or FIRST mode)
          "OK_ALL"→ multi_mode=ALL
    """
    assets = client.list_share_assets(share_id)
    if not assets:
        return ("NONE", [])

    asset_ids: List[str] = []
    for a in assets:
        aid = a.get("id") or a.get("asset_id")
        if isinstance(aid, str):
            asset_ids.append(aid)

    if len(asset_ids) <= 1:
        return ("OK", asset_ids)

    m = (multi_mode or "ERROR").upper()
    if m == "ERROR":
        return ("MULTI", asset_ids)
    if m == "FIRST":
        return ("OK", [asset_ids[0]])
    if m == "ALL":
        return ("OK_ALL", asset_ids)
    return ("MULTI", asset_ids)


def resolve_all_storage_paths(
    client: IconikClient,
    files: List[Dict[str, Any]],
    chosen: Dict[str, Any],
    output_mode: str,
    file_multi: str,
) -> List[str]:
    """
    Resolve storage paths for the chosen file and any detected replicas,
    then apply the file_multi preference (ERROR/FIRST/ALL).
    """
    urls: List[str] = []

    asset_id = chosen.get("asset_id") or chosen.get("asset") or chosen.get("parent_id")
    file_id = chosen.get("id") or chosen.get("file_id")
    if not file_id:
        raise RuntimeError("File object missing id.")

    resp = client.get_download_url(asset_id, file_id)
    urls.extend(extract_all_urls_from_response(resp))

    name = (chosen.get("filename") or chosen.get("name") or "").strip()
    size = chosen.get("size")
    checksum = (
        chosen.get("checksum") or chosen.get("md5") or chosen.get("sha1") or ""
    ).strip()

    replica_candidates: List[Dict[str, Any]] = []
    for f in files:
        if (f.get("id") or f.get("file_id")) == file_id:
            continue
        same_name = (f.get("filename") or f.get("name") or "").strip() == name and name != ""
        same_size = (f.get("size") == size and size not in (None, 0))
        same_checksum = False
        for ck in ("checksum", "md5", "sha1"):
            val = (f.get(ck) or "").strip()
            if val and checksum and val == checksum:
                same_checksum = True
                break
        if same_checksum or (same_name and same_size):
            replica_candidates.append(f)

    for f in replica_candidates[:10]:
        rid = f.get("id") or f.get("file_id")
        if not rid:
            continue
        try:
            r = client.get_download_url(asset_id, rid)
            urls.extend(extract_all_urls_from_response(r))
        except Exception:
            continue

    formatted: List[str] = []
    seen = set()
    for u in urls:
        out = Formatter.format(u, output_mode)
        if out not in seen:
            seen.add(out)
            formatted.append(out)

    m = (file_multi or "ALL").upper()
    if m == "ERROR" and len(formatted) > 1:
        raise RuntimeError(
            "Multiple storage locations were found for this file. "
            "You can change this behavior with --multi-files FIRST|ALL."
        )
    if m == "FIRST" and formatted:
        return [formatted[0]]
    return formatted


# ============================================================
# Single lookup
# ============================================================

def single_lookup(
    ui: UI,
    client: IconikClient,
    output_mode: str,
    share_multi: str,
    file_multi: str,
    link: str,
    as_json: bool,
    to_clip: bool,
):
    t, v = Resolver.parse_target(link)

    if t == "collection_url":
        raise RuntimeError(
            "The URL/share points to a collection of assets. Please provide a link to a single asset."
        )

    asset_ids: List[str] = []
    if t == "asset_id":
        asset_ids = [v]
        status = "OK"
    else:
        status, asset_ids = handle_assets_for_share(client, v, share_multi)

    if status == "NONE":
        raise RuntimeError(
            "Share does not resolve to an accessible asset. Please provide a link to a single asset."
        )
    if status == "MULTI":
        raise RuntimeError(
            "The URL/share points to a collection of assets. Please provide a link to a single asset."
        )

    results = []
    for aid in asset_ids:
        files = client.list_files(aid)
        chosen = Resolver.choose_file(files)
        paths = resolve_all_storage_paths(client, files, chosen, output_mode, file_multi)
        asset_meta = client.get_asset(aid) or {}
        title = asset_meta.get("title") or asset_meta.get("name") or ""
        results.append(
            {
                "asset_id": aid,
                "asset_title": title,
                "file_name": chosen.get("filename") or chosen.get("name") or "",
                "paths": paths,
            }
        )

    if as_json:
        ui.info(
            json.dumps(
                {
                    "mode": output_mode,
                    "share_multi": share_multi,
                    "file_multi": file_multi,
                    "assets": results,
                },
                ensure_ascii=False,
            )
        )
    else:
        if len(results) == 1:
            r = results[0]
            ui.box("Asset", f"{r['asset_title'] or '(untitled)'}\n{r['asset_id']}")
            ui.box("Selected file", r["file_name"] or "(unnamed)")
            out = (
                r["paths"][0] if len(r["paths"]) == 1 else "\n".join(r["paths"])
            )
            ui.box(
                "Output" if len(r["paths"]) == 1 else f"Outputs ({len(r['paths'])})",
                out,
            )
        else:
            ui.box(
                "Assets",
                f"{len(results)} assets (share handling: {share_multi}, file handling: {file_multi})",
            )
            for idx, r in enumerate(results, 1):
                body = f"{r['asset_title'] or '(untitled)'}\n{r['asset_id']}"
                ui.box(f"Asset {idx}", body)
                ui.box("Selected file", r["file_name"] or "(unnamed)")
                out = (
                    r["paths"][0] if len(r["paths"]) == 1 else "\n".join(r["paths"])
                )
                ui.box(
                    "Output" if len(r["paths"]) == 1 else f"Outputs ({len(r['paths'])})",
                    out,
                )

    if to_clip and results and results[0]["paths"]:
        if pbcopy(results[0]["paths"][0]):
            ui.note("Copied first path to clipboard.")
        else:
            ui.err("Couldn't copy to clipboard (pbcopy not available).")


# ============================================================
# Batch helpers
# ============================================================

def _read_any_with_pandas(path: str):
    import pandas as pd  # type: ignore

    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl"), True, ext
    if ext == ".tsv":
        return (
            pd.read_csv(
                path, sep="\t", dtype=str, keep_default_na=False, engine="python"
            ),
            False,
            ext,
        )
    return (
        pd.read_csv(path, dtype=str, keep_default_na=False, engine="python"),
        False,
        ext,
    )


def read_table(ui: UI, path: str):
    p = InputHelpers.sanitize_path(path)
    global HAS_PANDAS, pd
    if not HAS_PANDAS:
        ok = ensure_package_interactive(
            ["pandas", "openpyxl"],
            "pandas",
            "to read CSV/Excel files reliably",
            cancel_ok=True,
        )
        if not ok:
            raise RuntimeError("Batch mode requires pandas; user declined install.")
        import pandas as _pd  # type: ignore

        pd = _pd
        HAS_PANDAS = True

    import pandas as pd  # type: ignore

    try:
        df, is_xlsx, ext = _read_any_with_pandas(p)
        return df, is_xlsx, ext
    except Exception as e:
        raise RuntimeError(f"Failed to read '{p}': {e}")


def write_table(ui: UI, df, path: str, is_excel: bool, ext: str):
    """
    Robust writer for CSV/TSV/XLSX with a tmp file that preserves the extension.
    Fixes: Invalid extension for engine '...': 'tmp'
    """
    out = InputHelpers.sanitize_path(path)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    root, out_ext = os.path.splitext(out)
    if not out_ext:
        out_ext = ext or ".csv"
    tmp = root + ".tmp" + out_ext  # e.g., myfile.tmp.xlsx

    import pandas as pd  # type: ignore

    try:
        if out_ext.lower() in (".xlsx", ".xls") or is_excel:
            df.to_excel(tmp, index=False, engine="openpyxl")
        elif out_ext.lower() == ".tsv":
            df.to_csv(tmp, index=False, sep="\t", lineterminator="\n")
        else:
            df.to_csv(tmp, index=False, lineterminator="\n")

        os.replace(tmp, out)
        return out

    except Exception as e:
        ui.warn(f"Writing '{out}' failed: {e}")
        if ui.confirm("Write as CSV instead?", True):
            out_csv = root + ".csv"
            tmp_csv = root + ".tmp.csv"
            try:
                df.to_csv(tmp_csv, index=False, lineterminator="\n")
                os.replace(tmp_csv, out_csv)
                ui.note(f"Wrote CSV fallback: {out_csv}")
                return out_csv
            except Exception as e2:
                raise RuntimeError(f"CSV fallback also failed: {e2}")
        else:
            raise


def detect_header_and_column(ui: UI, df, sample_rows: int = 200):
    """
    Scores columns by how likely they are to contain links/UUIDs.
    We assume row 0 is header; we no longer ask for header row.
    """
    import pandas as pd  # type: ignore

    def score_series(s) -> float:
        total = max(1, len(s))
        matches = 0.0
        for val in list(s.astype(str).head(sample_rows)):
            val = val.strip()
            if not val:
                continue
            if UUID_RE.match(val):
                matches += 1
                continue
            if ASSET_URL_RE.match(val) or SHARE_URL_RE.match(val):
                matches += 1
                continue
            if "http" in val and ("asset/" in val or "/u/" in val or "icnk" in val):
                matches += 0.5
                continue
        return matches / total

    scores = {str(c): score_series(df[c].astype(str).fillna("")) for c in df.columns}
    best_col = max(scores, key=lambda k: scores[k]) if scores else None
    return best_col, scores


def choose_column(ui: UI, df) -> str:
    """
    Show preview, auto-detect the most likely link/ID column,
    then ask the user to confirm or override by index or name.
    """
    ui.note("Preview of first rows:")
    ui.table_preview(df, max_rows=6)

    best_col, scores = detect_header_and_column(ui, df)

    ui.note(
        "Columns (index : name) — detection score [0..1] & first-row sample:"
    )
    cols = list(map(str, df.columns))
    for i, c in enumerate(cols):
        sc = scores.get(c, 0.0)
        sample = str(df.iloc[0][c]) if len(df.index) > 0 else ""
        ui.info(f"{i}: {c}  [score={sc:.2f}]  sample='{sample}'")

    suggested = best_col if best_col in cols else (cols[0] if cols else "")
    raw_col = ui.ask(
        f"Which column contains the links or IDs you would like to locate? (Enter to use suggested: {suggested})",
        suggested,
    )

    col_name: Optional[str] = None
    if raw_col.isdigit():
        idx = int(raw_col)
        if 0 <= idx < len(cols):
            col_name = cols[idx]

    if col_name is None:
        if raw_col in cols:
            col_name = raw_col
        else:
            lowmap = {c.lower(): c for c in cols}
            col_name = lowmap.get(raw_col.lower())

    if not col_name:
        raise RuntimeError("Could not resolve the column selection.")
    return col_name


def batch_process(
    ui: UI,
    client: IconikClient,
    output_mode: str,
    share_multi: str,
    file_multi: str,
    in_path: str,
):
    p = InputHelpers.sanitize_path(in_path)
    try:
        df, is_excel, ext = read_table(ui, p)
    except Exception as e:
        ui.err(f"Could not read input: {e}")
        return

    try:
        col_name = choose_column(ui, df)
    except Exception as e:
        ui.err(f"Column selection failed: {e}")
        return

    default_out = os.path.join(
        os.path.dirname(p),
        os.path.splitext(os.path.basename(p))[0]
        + "_with_storage"
        + (ext if ext in (".csv", ".tsv") else ".xlsx"),
    )

    out_path = InputHelpers.sanitize_path(
        ui.ask(
            "Please confirm the output file path (Enter to use suggested)",
            default_out,
        )
    )
    if os.path.isdir(out_path):
        out_path = os.path.join(out_path, os.path.basename(default_out))

    storage_col = "StoragePath"
    error_col = "Error"
    multi_ins_col = "MultiInserted"
    multi_total_col = "MultiTotalAssets"
    asset_id_col = "AssetID"
    asset_title_col = "AssetTitle"

    for col in (
        storage_col,
        error_col,
        multi_ins_col,
        multi_total_col,
        asset_id_col,
        asset_title_col,
    ):
        if col not in df.columns:
            df[col] = ""

    rows_out: List[Dict[str, Any]] = []
    total = len(df.index)
    prog = ui.progress()
    successes = failures = 0

    def process_asset_for_row(
        row_dict: Dict[str, Any], asset_id: str, is_inserted: bool, total_assets: int
    ) -> Dict[str, Any]:
        files = client.list_files(asset_id)
        chosen = Resolver.choose_file(files)
        paths = resolve_all_storage_paths(
            client, files, chosen, output_mode, file_multi
        )
        meta = client.get_asset(asset_id) or {}
        title = meta.get("title") or meta.get("name") or ""
        out_row = dict(row_dict)
        out_row[asset_id_col] = asset_id
        out_row[asset_title_col] = title
        out_row[storage_col] = format_multi_for_cell(paths)
        out_row[error_col] = ""
        out_row[multi_ins_col] = "Y" if is_inserted else ""
        out_row[multi_total_col] = str(total_assets) if total_assets > 1 else ""
        return out_row

    iterator = range(total)

    def process_index(idx: int):
        nonlocal successes, failures
        try:
            raw_val = str(df.iloc[idx][col_name]).strip()
            base_row = df.iloc[idx].to_dict()
            if not raw_val:
                base_row[error_col] = "Empty input"
                rows_out.append(base_row)
                failures += 1
                return
            t, v = Resolver.parse_target(raw_val)
            if t == "collection_url":
                base_row[
                    error_col
                ] = "The URL/share points to a collection of assets. Please provide a link to a single asset."
                rows_out.append(base_row)
                failures += 1
                return
            if t == "asset_id":
                rows_out.append(
                    process_asset_for_row(base_row, v, False, 1)
                )
                successes += 1
                return

            status, asset_ids = handle_assets_for_share(client, v, share_multi)
            if status == "NONE":
                base_row[
                    error_col
                ] = "Share does not resolve to an accessible asset. Please provide a link to a single asset."
                rows_out.append(base_row)
                failures += 1
            elif status == "MULTI":
                base_row[
                    error_col
                ] = "The URL/share points to a collection of assets. Please provide a link to a single asset."
                base_row[multi_total_col] = str(len(asset_ids))
                rows_out.append(base_row)
                failures += 1
            elif status == "OK":
                rows_out.append(
                    process_asset_for_row(base_row, asset_ids[0], False, len(asset_ids))
                )
                successes += 1
            elif status == "OK_ALL":
                first = True
                for aid in asset_ids:
                    try:
                        rows_out.append(
                            process_asset_for_row(
                                base_row, aid, (not first), len(asset_ids)
                            )
                        )
                        successes += 1
                    except Exception as e:
                        err_row = dict(base_row)
                        err_row[error_col] = str(e)
                        err_row[multi_ins_col] = "Y" if not first else ""
                        err_row[multi_total_col] = str(len(asset_ids))
                        rows_out.append(err_row)
                        failures += 1
                    first = False
            else:
                base_row[error_col] = "Unexpected multi-asset state."
                rows_out.append(base_row)
                failures += 1
        except Exception as e:
            row = df.iloc[idx].to_dict()
            row[error_col] = str(e)
            rows_out.append(row)
            failures += 1

    if prog:
        with prog:
            task = prog.add_task("Resolving", total=total)
            for idx in iterator:
                process_index(idx)
                prog.update(task, advance=1)
    else:
        for idx in iterator:
            process_index(idx)

    import pandas as pd  # type: ignore

    df_out = pd.DataFrame(
        rows_out,
        columns=list(df.columns)
        + [
            asset_id_col,
            asset_title_col,
            storage_col,
            error_col,
            multi_ins_col,
            multi_total_col,
        ],
    )
    try:
        write_table(ui, df_out, out_path, is_excel, os.path.splitext(out_path)[1].lower())
    except Exception as e:
        ui.err(f"Could not write the output file: {e}")
        return

    ui.box(
        "Batch complete",
        f"Saved: {out_path}\nSuccess: {successes}\nFailed: {failures}\n"
        "Review 'Error' and 'MultiInserted' columns for details.",
    )


# ============================================================
# CLI args, pbcopy, multi normalization
# ============================================================

def parse_args(argv: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "reset": False,
        "host": None,
        "output": None,
        "json": False,
        "copy": False,
        "version": False,
        "reset_prompts": False,
        "multi_share": None,
        "multi_files": None,
    }
    i = 0
    L = len(argv)
    while i < L:
        a = argv[i]
        if a in ("--reset", "-r"):
            out["reset"] = True
        elif a == "--host" and i + 1 < L:
            out["host"] = argv[i + 1]
            i += 1
        elif a == "--output" and i + 1 < L:
            out["output"] = argv[i + 1]
            i += 1
        elif a == "--json":
            out["json"] = True
        elif a == "--copy":
            out["copy"] = True
        elif a in ("--version", "-V"):
            out["version"] = True
        elif a == "--reset-prompts":
            out["reset_prompts"] = True
        elif a == "--multi" and i + 1 < L:
            out["multi_share"] = argv[i + 1]
            i += 1
        elif a == "--multi-files" and i + 1 < L:
            out["multi_files"] = argv[i + 1]
            i += 1
        i += 1
    return out


def normalize_multi(val: Optional[str], current: Optional[str], default: str) -> str:
    v = (val or current or default).strip().upper()
    if v not in ("ERROR", "FIRST", "ALL"):
        v = default
    return v


def pbcopy(text: str) -> bool:
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-8"))
        return p.returncode == 0
    except Exception:
        return False


# ============================================================
# Main
# ============================================================

def main():
    # Offer Rich UI if not already installed (once)
    suppress = bool(ConfigStore.get_flag("suppress_rich_prompt", False))
    global RICH, Console, Panel, Text, Theme, Table, Progress
    if not RICH and not suppress:
        ok = ensure_package_interactive(
            ["rich"], "rich", "for a clearer, high-contrast UI", cancel_ok=True
        )
        if ok:
            from rich.console import Console as _Console  # type: ignore
            from rich.panel import Panel as _Panel  # type: ignore
            from rich.text import Text as _Text  # type: ignore
            from rich.theme import Theme as _Theme  # type: ignore
            from rich.table import Table as _Table  # type: ignore
            from rich.progress import (  # type: ignore
                Progress as _Progress,
                BarColumn,
                TextColumn,
                TimeElapsedColumn,
            )

            Console, Panel, Text, Theme, Table, Progress = (
                _Console,
                _Panel,
                _Text,
                _Theme,
                _Table,
                _Progress,
            )
            RICH = True
        else:
            ConfigStore.set_flag("suppress_rich_prompt", True)

    ui = UI()
    ui.banner(f"iconik storage locator {VERSION}")

    args = parse_args(sys.argv[1:])
    if args["version"]:
        ui.info(VERSION)
        return
    if args["reset_prompts"]:
        ConfigStore.set_flag("suppress_rich_prompt", False)
        ui.note("Prompt preferences reset.")
    if args["reset"]:
        if ConfigStore.reset():
            ui.info("Saved credentials and preferences removed.")
        else:
            ui.note("No saved credentials found.")

    app_id, token, host, output_mode, share_multi, file_multi, prefs_init = (
        ConfigStore.load()
    )

    if args["host"]:
        host = args["host"]
    if args["output"]:
        output_mode = args["output"].upper()

    # Apply CLI multi overrides (for this run + store)
    if args["multi_share"]:
        share_multi = normalize_multi(args["multi_share"], share_multi, "ERROR")
        ConfigStore.set(multi_share=share_multi, multi=share_multi)
    if args["multi_files"]:
        file_multi = normalize_multi(args["multi_files"], file_multi, "ALL")
        ConfigStore.set(file_multi=file_multi)

    # Gather core connection info
    if not host:
        host = ui.ask("Host", "https://app.iconik.io")
    if not app_id:
        app_id = ui.ask("App-ID")
    if not token:
        token = InputHelpers.masked_input("Auth-Token: ")
    if not output_mode:
        output_mode = ui.ask("Output (HTTPS|S3|FULL)", "HTTPS").upper()

    if not app_id or not token:
        ui.err("App-ID and Auth-Token are required.")
        return

    # First-run-style multi preferences (only when missing)
    if not share_multi:
        raw = ui.ask(
            "How should Iconik Storage Locator handle share links that resolve to multiple assets?\n"
            "  ERROR – show an error and ask for a single asset\n"
            "  FIRST – resolve the first asset in the share\n"
            "  ALL   – resolve all assets in the share\n"
            "Enter ERROR, FIRST, or ALL (default: ERROR)",
            "ERROR",
        )
        share_multi = normalize_multi(raw, None, "ERROR")
        ConfigStore.set(multi_share=share_multi, multi=share_multi)

    if not file_multi:
        raw = ui.ask(
            "If an asset's original file is stored in multiple locations (replicas), how should we handle it?\n"
            "  ERROR – show an error\n"
            "  FIRST – use the first location\n"
            "  ALL   – return all locations\n"
            "Enter ERROR, FIRST, or ALL (default: ALL)",
            "ALL",
        )
        file_multi = normalize_multi(raw, None, "ALL")
        ConfigStore.set(file_multi=file_multi)

    # Mark prefs initialized (v2.0.3)
    ConfigStore.set(multi_prefs_initialized=True)

    # Save connection defaults (host/app_id/token/output) if changed
    prev_app, prev_tok, prev_host, prev_output, _, _, _ = ConfigStore.load()
    if (
        app_id,
        token,
        host,
        output_mode,
    ) != (prev_app, prev_tok, prev_host, prev_output):
        if ConfigStore.get_flag("first_save_done", False) or ui.confirm(
            "Save/update App-ID/Auth-Token/host/output as defaults for next time?",
            True,
        ):
            ConfigStore.set(
                app_id=app_id,
                auth_token=token,
                host=host.rstrip("/"),
                output=output_mode.upper(),
            )
            ConfigStore.set_flag("first_save_done", True)
            ui.note("Connection defaults saved.")

    ui.note(
        f"Host: {host}  Output: {output_mode}  "
        f"Share multi: {share_multi} ({describe_share_multi(share_multi)})  "
        f"File multi: {file_multi} ({describe_file_multi(file_multi)})"
    )

    client = IconikClient(host, app_id, token)

    first_loop = True
    while True:
        if first_loop:
            ui.info("Welcome to Iconik Storage Locator!")
            first_loop = False

        raw = ui.ask(
            "Please paste an Iconik asset URL, share URL, asset UUID, "
            "OR drop a CSV/XLSX file with a list of them (q=quit)"
        ).strip()

        if not raw or raw.lower() in ("q", "quit", "exit"):
            ui.info("Goodbye!")
            return

        # Allow interactive multi preference updates
        parts = raw.split()
        if parts and parts[0] in ("--multi", "--multi-files"):
            if len(parts) < 2:
                ui.err(
                    "Please provide a mode after "
                    "--multi / --multi-files (ERROR, FIRST, or ALL)."
                )
                continue

            mode_str = parts[1].upper()
            if mode_str not in ("ERROR", "FIRST", "ALL"):
                ui.err("Invalid mode. Please use ERROR, FIRST, or ALL.")
                continue

            if parts[0] == "--multi":
                share_multi = mode_str
                ConfigStore.set(multi_share=share_multi, multi=share_multi)
                ui.note(
                    f"Multi-asset share handling updated to: {share_multi} "
                    f"({describe_share_multi(share_multi)})."
                )
            else:
                file_multi = mode_str
                ConfigStore.set(file_multi=file_multi)
                ui.note(
                    f"Multi-source file handling updated to: {file_multi} "
                    f"({describe_file_multi(file_multi)})."
                )

            # If there's more on the line, treat it as the actual input
            if len(parts) > 2:
                inp = " ".join(parts[2:])
            else:
                # Only preference update this round
                continue
        else:
            inp = raw

        if InputHelpers.is_list_file(inp):
            try:
                batch_process(
                    ui, client, output_mode, share_multi, file_multi, inp
                )
            except PermissionError as e:
                ui.err(
                    f"{e}\nAsk an iconik admin to grant access "
                    "(read asset/files and allow original downloads)."
                )
            except FileNotFoundError:
                ui.err("Object not found. Check the link/ID and your access.")
            except requests.RequestException as e:
                ui.err(f"Network error: {e}")
            except Exception as e:
                ui.err(f"Batch failed: {e}")
        else:
            try:
                single_lookup(
                    ui,
                    client,
                    output_mode,
                    share_multi,
                    file_multi,
                    inp,
                    as_json=args["json"],
                    to_clip=args["copy"],
                )
            except PermissionError as e:
                ui.err(
                    f"{e}\nAsk an iconik admin to grant access "
                    "(read asset/files and allow original downloads)."
                )
            except FileNotFoundError:
                ui.err("Object not found. Check the link/ID and your access.")
            except requests.RequestException as e:
                ui.err(f"Network error: {e}")
            except Exception as e:
                ui.err(str(e))

        if not ui.confirm("Would you like to look up another?", True):
            ui.info("Done.")
            return


if __name__ == "__main__":
    main()
