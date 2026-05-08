"""Shared logic for driving the Bitwarden CLI.

Used by `bwexport.cli` (headless) and `bwexport.gui` (Tkinter). All bw subprocess
invocations, secret handling, session lifecycle, collection lookup, and CSV
serialization live here.

Security model:
- API key (BW_CLIENTID/BW_CLIENTSECRET) lives in the OS credential store via
  `keyring` — Windows Credential Manager (DPAPI) on Windows, macOS Keychain
  on macOS. Never written to disk in plaintext.
- Master password is provided per-call by the caller (interactively from
  GUI/CLI) and passed to bw via --passwordenv, never via argv.
- BW_SESSION is held in memory by the caller and passed via env to subprocesses.
- Output CSV is created with restrictive permissions (0600 on POSIX,
  ACL inheritance off + current-user-only on Windows).
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

try:
    import keyring
except ImportError:
    keyring = None

KEYRING_SERVICE = "bwexport"

BW_CSV_COLUMNS = [
    "collections", "type", "name", "notes", "fields", "reprompt",
    "login_uri", "login_username", "login_password", "login_totp",
]

ITEM_TYPES = {1: "login", 2: "note", 3: "card", 4: "identity"}

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class BWError(RuntimeError):
    """A bw CLI invocation failed or returned unexpected output."""


def _bw_executable() -> str:
    if os.name == "nt" and which("bw.cmd"):
        return "bw.cmd"
    return "bw"


def run_bw(args, *, env_extra=None, check=True) -> subprocess.CompletedProcess:
    """Invoke bw. Secrets travel via env or stdin — never argv."""
    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(
        [_bw_executable(), *args], env=env,
        capture_output=True, text=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    if check and proc.returncode != 0:
        raise BWError(f"bw {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def ensure_bw_installed():
    if which("bw") is None and which("bw.cmd") is None:
        raise BWError(
            "bw CLI not found on PATH. Install with one of:\n"
            "  winget install Bitwarden.CLI\n"
            "  scoop install bitwarden-cli\n"
            "  npm i -g @bitwarden/cli\n"
            "(macOS: brew install bitwarden-cli)"
        )


# --- Keyring (API key storage) ---

def keyring_get_api_key() -> tuple[str | None, str | None]:
    if keyring is None:
        return None, None
    return (
        keyring.get_password(KEYRING_SERVICE, "client_id"),
        keyring.get_password(KEYRING_SERVICE, "client_secret"),
    )


def keyring_set_api_key(client_id: str, client_secret: str):
    if keyring is None:
        raise BWError("keyring library not available — pip install keyring")
    keyring.set_password(KEYRING_SERVICE, "client_id", client_id)
    keyring.set_password(KEYRING_SERVICE, "client_secret", client_secret)


def keyring_delete_api_key():
    if keyring is None:
        return
    for k in ("client_id", "client_secret"):
        try:
            keyring.delete_password(KEYRING_SERVICE, k)
        except Exception:
            pass


# --- bw lifecycle ---

def configure_server(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BWError(f"invalid server URL: {url!r}")
    run_bw(["config", "server", url])


def status() -> dict:
    return json.loads(run_bw(["status"]).stdout)


def login_apikey(client_id: str, client_secret: str):
    run_bw(["login", "--apikey"], env_extra={
        "BW_CLIENTID": client_id, "BW_CLIENTSECRET": client_secret,
    })


def unlock(master_password: str) -> str:
    """Returns BW_SESSION. Master password passes via env, not argv."""
    proc = run_bw(
        ["unlock", "--passwordenv", "BW_PW", "--raw"],
        env_extra={"BW_PW": master_password},
    )
    return proc.stdout.strip()


def lock(session: str | None = None):
    env = {"BW_SESSION": session} if session else None
    run_bw(["lock"], env_extra=env, check=False)


def logout():
    run_bw(["logout"], check=False)


def sync(session: str):
    run_bw(["sync"], env_extra={"BW_SESSION": session})


def list_org_collections(session: str, org_id: str) -> list[dict]:
    proc = run_bw(
        ["list", "org-collections", "--organizationid", org_id],
        env_extra={"BW_SESSION": session},
    )
    return json.loads(proc.stdout)


def list_collection_items(session: str, org_id: str, collection_id: str) -> list[dict]:
    proc = run_bw(
        ["list", "items", "--organizationid", org_id, "--collectionid", collection_id],
        env_extra={"BW_SESSION": session},
    )
    return json.loads(proc.stdout)


@contextmanager
def session_context(client_id: str, client_secret: str, master_password: str):
    """Login if needed, unlock, yield session, lock+logout on exit."""
    fresh_login = status().get("status") == "unauthenticated"
    if fresh_login:
        login_apikey(client_id, client_secret)
    session = unlock(master_password)
    try:
        yield session
    finally:
        lock(session)
        if fresh_login:
            logout()


# --- CSV serialization ---

def _encode_fields(fields):
    if not fields:
        return ""
    return "\n".join(f"{f.get('name', '')}: {f.get('value', '')}" for f in fields)


def item_to_row(item: dict, collection_name: str) -> dict:
    login = item.get("login") or {}
    uris = [u.get("uri", "") for u in (login.get("uris") or []) if u.get("uri")]
    return {
        "collections": collection_name,
        "type": ITEM_TYPES.get(item.get("type", 1), "login"),
        "name": item.get("name") or "",
        "notes": item.get("notes") or "",
        "fields": _encode_fields(item.get("fields")),
        "reprompt": 1 if item.get("reprompt") else 0,
        "login_uri": ",".join(uris),
        "login_username": login.get("username") or "",
        "login_password": login.get("password") or "",
        "login_totp": login.get("totp") or "",
    }


def write_csv(items: list[dict], collection_name: str, out_path: str | Path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            _write_rows(f, items, collection_name)
        _restrict_acl_windows(out_path)
    else:
        fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            _write_rows(f, items, collection_name)


def _write_rows(fileobj, items, collection_name):
    w = csv.DictWriter(fileobj, fieldnames=BW_CSV_COLUMNS)
    w.writeheader()
    for item in items:
        w.writerow(item_to_row(item, collection_name))


def _restrict_acl_windows(path: Path):
    """Strip inherited ACLs and grant Full Control only to the current user."""
    user = os.environ.get("USERNAME") or ""
    if not user:
        return
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
        capture_output=True, check=False,
        creationflags=_CREATE_NO_WINDOW,
    )


# --- High-level helpers ---

def filter_collections(collections: list[dict], query: str) -> list[dict]:
    """Substring match (case-insensitive). Empty query returns everything."""
    if not query:
        return list(collections)
    q = query.lower()
    return [c for c in collections if q in c["name"].lower()]
