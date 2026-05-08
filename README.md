# bwexport

Per-collection password export for self-hosted Bitwarden organizations. Built for the MSP workflow where one Bitwarden org holds collections for many clients, but a handover needs to ship just *one* client's data — something Bitwarden's built-in export can't do.

Output is Bitwarden-compatible CSV that can be re-imported into any Bitwarden vault.

---

## Repo layout

| Path | Purpose |
| --- | --- |
| `bwexport/core.py` | bw CLI driver, secret handling, CSV serialization |
| `bwexport/cli.py` | headless CLI for scripted runs |
| `bwexport/gui.py` | Tkinter GUI for interactive Windows use |
| `run_gui.py` | PyInstaller / direct-run launcher for the GUI |
| `build_windows.ps1` | builds `dist\bwexport.exe` |
| `pyproject.toml` | Python packaging metadata |

---

## Prerequisites

You need three things before bwexport can do anything useful:

1. **Your Bitwarden server URL** — e.g. `https://bitwarden.example.com`. The same one you log into in a browser.
2. **Your organization's UUID** — see [Finding your Organization ID](#finding-your-organization-id) below.
3. **A personal API key** — see [Getting your API key](#getting-your-api-key) below.

You'll also need:

- Bitwarden CLI (`bw`) on PATH on whatever machine actually runs the export.
- Python 3.11+ on whatever machine builds the `.exe` (only needed once, only on the build machine).

---

## Install on Windows (typical deployment)

You have two paths. Pick one.

### Path A — Build directly on the target server (simplest)

If the target server already has internet access and you're OK installing Python on it (e.g. a tools host or a dedicated admin VM), do the whole thing in place:

```powershell
# 1. Install dependencies (one-time)
winget install Git.Git
winget install Python.Python.3.12
winget install Bitwarden.CLI

# 2. Clone and build
git clone https://github.com/shuckyd/bwexport.git C:\Tools\bwexport
cd C:\Tools\bwexport
.\build_windows.ps1

# 3. Run
.\dist\bwexport.exe
```

`bwexport.exe` is the only file you need to keep around — pin it to the taskbar or drop a shortcut on the desktop.

### Path B — Build on a workstation, copy `.exe` to the server

If the target server is locked down (no Python, no winget, restricted internet), build elsewhere and copy:

```powershell
# On a Windows workstation with Python:
git clone https://github.com/shuckyd/bwexport.git
cd bwexport
.\build_windows.ps1
# → dist\bwexport.exe is produced

# Then on the target server:
winget install Bitwarden.CLI       # bw CLI is still required at runtime
# Copy dist\bwexport.exe to the server (file share, USB, RDP clipboard, etc.)
# Run it.
```

The target server only needs **`bw.exe` on PATH** and the `.exe`. No Python, no Git.

---

## Updating to a newer version

```powershell
cd C:\Tools\bwexport
git pull
.\build_windows.ps1
```

Or, for Path B deployments, rebuild on your workstation and copy the new `dist\bwexport.exe` over the old one.

---

## Configuration

### Finding your Organization ID

Two ways:

**From the web vault (easiest):**
Log into your Bitwarden web vault, click on the organization in the left sidebar. The URL bar will look like:

```
https://bitwarden.example.com/#/organizations/abc12345-6789-...-xyz/vault
```

Copy the UUID (`abc12345-6789-...-xyz`). That's your organization ID.

**From the CLI:**

```powershell
bw config server https://bitwarden.example.com
bw login                            # interactive — email + master password + 2FA
bw list organizations
```

Returns JSON; the `id` field of your org is the UUID.

### Getting your API key

In the Bitwarden web vault:

1. Click your **account icon** (top-right) → **Account settings**.
2. Go to **Security** → **Keys**.
3. Click **View API key**. Bitwarden will prompt for your master password.
4. Copy `client_id` and `client_secret`.

These are *your personal* API key, not the organization's API key. bwexport uses them with `bw login --apikey` to authenticate as you.

### First run of `bwexport.exe`

1. **Server URL** — paste the URL of your self-hosted Bitwarden.
2. **Organization ID** — paste the UUID from above.
3. Click **Save settings**. (Stored at `%APPDATA%\bwexport\config.json`. These are not secrets.)
4. Click **API key…**, paste `client_id` and `client_secret`. (Stored in **Windows Credential Manager** under service name `bwexport`, encrypted with DPAPI.)
5. Click **Unlock vault**. Enter your master password. The vault syncs and the collection list populates.
6. Type in the filter, click a collection, **Export selected to CSV…**. Default filename is `<client>-<YYYY-MM-DD>.csv`.
7. Click **Lock** when done (or close the window — it auto-locks on exit).

---

## Headless CLI usage

Useful for scheduled exports or scripted runs:

```bash
pip install .
bwexport \
  --server https://bitwarden.example.com \
  --org-id <organization-uuid> \
  --client "Acme Corp" \
  --out acme.csv
```

First run prompts for the API key and offers to store it in the OS credential store (Windows Credential Manager / macOS Keychain). Subsequent runs only prompt for the master password.

---

## Security model

- **API key** lives in the OS credential store (Windows Credential Manager via DPAPI; macOS Keychain). Never written to disk in plaintext.
- **Master password** is prompted interactively on every unlock, passed to `bw` via `--passwordenv`. Never via argv (so it doesn't leak via `ps`/Process Explorer), never stored.
- **`BW_SESSION`** is held in process memory only.
- **Output CSV** is created with restrictive ACLs — current user only on Windows (`icacls /inheritance:r /grant:r`), `0600` on POSIX.
- **`bw lock`** and **`bw logout`** run on every exit path, including window close.

### ⚠ The CSV is plaintext passwords

Bitwarden's CSV import format requires it. Before transmission to a client:

- Encrypt with `age` or `gpg` for the recipient.
- Or extend the tool to emit Bitwarden's `encrypted_json` format (small change, hasn't been needed yet).
- Shred the CSV after handover.

---

## Troubleshooting

**"bw CLI not found on PATH"** — `winget install Bitwarden.CLI` (or `npm i -g @bitwarden/cli`). Restart the GUI after installing.

**"Invalid master password"** when unlocking, but you're sure it's right — your account may need an email-code 2FA login first. Run `bw login` interactively in a terminal once to clear any pending 2FA prompt; bwexport's API-key login won't trigger it after that.

**Unlock succeeds but the collection list is empty** — your account may not have access to the org you specified, or the org UUID is wrong. Re-check it from the web vault URL.

**"Multiple collections matched"** in the CLI — your `--client` substring matched more than one collection. Use a more specific name, or copy-paste the exact collection name.

**Build fails with `keyring.backends.Windows` not found in the bundled `.exe`** — rebuild with the explicit hidden-import flag (already in `build_windows.ps1`). If it still fails, delete `build/` and `dist/` and rebuild with `--clean`.

**The exported CSV has fields/columns that don't import cleanly into another Bitwarden vault** — verify you're using the *organization* import format on the receiving end, not the personal-vault format. The two have slightly different column expectations.

---

## Roadmap / future additions

- **PDF output** for printable handover docs (ReportLab on top of the same item-fetch logic).
- **Multi-collection batch export** — one CSV per selected collection in a single run.
- **Encrypted JSON output** as a safer alternative to plaintext CSV when both ends are Bitwarden.
- **Dry-run / preview mode** — list items in a collection without writing the CSV.
