# bwexport

Per-collection password export for self-hosted Bitwarden organizations. Built for the MSP workflow where one Bitwarden org holds collections for many clients, but a handover needs to ship just *one* client's data — something Bitwarden's built-in export can't do.

Output is Bitwarden-compatible CSV, importable into any Bitwarden vault.

## Repo layout

- `bwexport/core.py` — bw CLI driver, secret handling, CSV serialization.
- `bwexport/cli.py` — headless CLI for scripted runs.
- `bwexport/gui.py` — Tkinter GUI for interactive use.
- `run_gui.py` — PyInstaller / direct-run launcher for the GUI.
- `build_windows.ps1` — produces `dist\bwexport.exe`.

## Build the Windows GUI

On any Windows machine with Python 3.11+:

```powershell
winget install Python.Python.3.12
winget install Bitwarden.CLI
git clone https://github.com/shuckyd/bwexport.git
cd bwexport
.\build_windows.ps1
```

Output: `dist\bwexport.exe`. That single file is what gets deployed — copy it anywhere on the target Windows server. The `bw` CLI must also be on the target's PATH (`winget install Bitwarden.CLI`).

## First-run flow (GUI)

1. Open `bwexport.exe`.
2. Fill in **Server URL** and **Organization ID**, click **Save settings**. Stored in `%APPDATA%\bwexport\config.json` — these aren't secrets.
3. Click **API key…**, paste your `BW_CLIENTID` / `BW_CLIENTSECRET` (web vault → Account settings → Security → Keys → View API key). Stored in **Windows Credential Manager** under service name `bwexport`.
4. Click **Unlock vault**, enter master password. Vault syncs and the collection list populates.
5. Type in the filter, click a collection, **Export selected to CSV…**. Default filename is `<client>-<YYYY-MM-DD>.csv`.
6. **Lock** before walking away (or just close the window — it locks on exit).

## Headless CLI usage

Useful for scheduled exports or scripted runs. Same install:

```bash
pip install .
bwexport \
  --server https://bitwarden.example.com \
  --org-id <organization-uuid> \
  --client "Acme Corp" \
  --out acme.csv
```

First run prompts for the API key and offers to store it in the OS credential store.

## Security model

- **API key** lives in the OS credential store (Windows Credential Manager via DPAPI; macOS Keychain). Never written to disk in plaintext.
- **Master password** is prompted interactively every unlock; passed to `bw` via `--passwordenv`, never via argv (so it doesn't leak via `ps`/Process Explorer).
- **`BW_SESSION`** lives in process memory only.
- **Output CSV** is created with restrictive ACLs — current user only on Windows (`icacls /inheritance:r /grant:r`), `0600` on POSIX.
- **`bw lock`** and **`bw logout`** run on every exit path, including window close.

## ⚠ The CSV is plaintext passwords

Bitwarden's import format requires it. Before transmission to a client:

- Encrypt with `age` or `gpg` for the recipient.
- Or extend the tool to emit Bitwarden's `encrypted_json` format (small change, hasn't been needed yet).
- Shred the CSV after handover.

## Future additions worth considering

- **PDF output** for printable handover docs (ReportLab on top of the same item-fetch logic).
- **Multi-collection export** — currently one at a time by design.
- **Encrypted JSON output** as a Bitwarden-to-Bitwarden alternative to plaintext CSV.
