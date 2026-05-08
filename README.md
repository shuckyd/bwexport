# bwexport

A small utility for exporting a single collection from a Bitwarden organization as a Bitwarden-compatible CSV. Bitwarden's built-in organization export operates on the whole org at once; bwexport scopes it down to one collection at a time.

Ships as a Tkinter GUI (built into a single Windows `.exe`) and as a headless CLI for scripted use.

> **Status: work in progress.** This is an experimental tool under active development. It is provided **as is**, with **no warranty** of any kind, express or implied. Verify behavior against a non-production vault before using it on real data. The author(s) and contributors assume **no liability** for data loss, security incidents, or any other consequences arising from its use. The MIT License (see `LICENSE`) governs distribution and includes the standard liability disclaimer; this notice is a reminder, not a substitute.

---

## Repo layout

| Path | Purpose |
| --- | --- |
| `bwexport/core.py` | bw CLI driver, secret handling, CSV serialization |
| `bwexport/cli.py` | headless CLI for scripted runs |
| `bwexport/gui.py` | Tkinter GUI |
| `run_gui.py` | PyInstaller / direct-run launcher for the GUI |
| `build_windows.ps1` | local build script — produces `dist\bwexport.exe` |
| `.github/workflows/build.yml` | CI build on every push and every `v*` tag |
| `pyproject.toml` | Python packaging metadata |

---

## Prerequisites

You need three things before bwexport can do anything useful:

1. **Your Bitwarden server URL** — e.g. `https://bitwarden.example.com`. The same URL you log into in a browser.
2. **An organization UUID** — see [Finding an Organization ID](#finding-an-organization-id) below.
3. **A personal API key** — see [Getting your API key](#getting-your-api-key) below.

You'll also need:

- **Bitwarden CLI (`bw`) on PATH** on whatever machine actually runs the export.
- **Python 3.11+** on whatever machine builds the `.exe` (only needed once, only on the build machine — not on the runtime machine if you use Path A below).

---

## Install on Windows

Three install paths. Pick whichever matches the target machine.

### Path A — Download the prebuilt `.exe` from Releases

GitHub Actions builds `bwexport.exe` on every tagged release. The target machine needs **only the bw CLI and `bwexport.exe`** — no Python, no Git, no build tooling.

1. **Install the Bitwarden CLI.** Either download the zip from <https://bitwarden.com/download/> ("Command line" → Windows) and put `bw.exe` on PATH, or paste this in PowerShell as Administrator:

    ```powershell
    $dest = "C:\Tools\bw"
    $zip  = "$env:TEMP\bw-cli.zip"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Invoke-WebRequest -Uri "https://vault.bitwarden.com/download/?app=cli&platform=windows" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Remove-Item $zip
    [Environment]::SetEnvironmentVariable(
        "Path",
        [Environment]::GetEnvironmentVariable("Path","Machine") + ";$dest",
        "Machine"
    )
    ```

2. **Download `bwexport.exe`.** Either visit <https://github.com/shuckyd/bwexport/releases/latest> in a browser, or pull it directly with PowerShell:

    ```powershell
    Invoke-WebRequest `
      -Uri "https://github.com/shuckyd/bwexport/releases/latest/download/bwexport.exe" `
      -OutFile "C:\Tools\bwexport.exe"
    ```

3. **Run it.** Double-click `C:\Tools\bwexport.exe` (open a fresh PowerShell window first so the new `PATH` is picked up).

### Path B — Build directly on the target machine

If the target machine has Python and you'd rather build from source than wait on CI:

```powershell
winget install Git.Git
winget install Python.Python.3.12
winget install Bitwarden.CLI

git clone https://github.com/shuckyd/bwexport.git C:\Tools\bwexport
cd C:\Tools\bwexport
.\build_windows.ps1

.\dist\bwexport.exe
```

### Path C — Build on a workstation, copy `.exe` to the target

Same as Path B, but build on a Windows workstation and copy `dist\bwexport.exe` to the target machine. The target still needs the bw CLI from Path A step 1.

---

## Updating

- **Path A (download .exe):** grab the new `bwexport.exe` from <https://github.com/shuckyd/bwexport/releases/latest> and overwrite the old one.
- **Path B/C (build from source):** `git pull` and re-run `.\build_windows.ps1`.

To cut a new release that CI will build automatically:

```bash
git tag v0.1.1
git push --tags
```

The `Build Windows EXE` workflow builds the exe and attaches it to a release with that tag.

---

## Configuration

### Finding an Organization ID

Two ways:

**From the web vault (easiest):** Log into your Bitwarden web vault, click the organization in the left sidebar. The URL bar will look like:

```
https://bitwarden.example.com/#/organizations/abc12345-6789-...-xyz/vault
```

Copy the UUID. That's the organization ID.

**From the CLI:**

```powershell
bw config server https://bitwarden.example.com
bw login                            # interactive — email + master password + 2FA
bw list organizations
```

The `id` field of your org in the JSON response is the UUID.

### Getting your API key

In the Bitwarden web vault:

1. Click your **account icon** (top-right) → **Account settings**.
2. Go to **Security** → **Keys**.
3. Click **View API key**. Bitwarden will prompt for your master password.
4. Copy `client_id` and `client_secret`.

These are *your personal* API key, not the organization's. bwexport uses them with `bw login --apikey` to authenticate as you.

### First run of `bwexport.exe`

1. **Server URL** — paste the URL of your Bitwarden server.
2. **Organization ID** — paste the UUID from above.
3. Click **Save settings**. (Stored at `%APPDATA%\bwexport\config.json`. Not secrets.)
4. Click **API key…**, paste `client_id` and `client_secret`. (Stored in **Windows Credential Manager** under service name `bwexport`, encrypted with DPAPI.)
5. Click **Unlock vault**. Enter your master password. The vault syncs and the collection list populates.
6. Type in the filter, click a collection, **Export selected to CSV…**. Default filename is `<collection>-<YYYY-MM-DD>.csv`.
7. Click **Lock** when done (or close the window — it auto-locks on exit).

---

## Headless CLI usage

```bash
pip install .
bwexport \
  --server https://bitwarden.example.com \
  --org-id <organization-uuid> \
  --client "<collection-name-or-substring>" \
  --out export.csv
```

First run prompts for the API key and offers to store it in the OS credential store (Windows Credential Manager / macOS Keychain). Subsequent runs only prompt for the master password.

---

## Security model

- **API key** lives in the OS credential store (Windows Credential Manager via DPAPI; macOS Keychain). Never written to disk in plaintext.
- **Master password** is prompted interactively on every unlock, passed to `bw` via `--passwordenv`. Never via argv (so it doesn't leak via `ps`/Process Explorer), never stored.
- **`BW_SESSION`** is held in process memory only.
- **Output CSV** is created with restrictive ACLs — current user only on Windows (`icacls /inheritance:r /grant:r`), `0600` on POSIX.
- **`bw lock`** and **`bw logout`** run on every exit path, including window close.

### The CSV is plaintext passwords

Bitwarden's CSV import format is plaintext by definition. Treat the output file as sensitive:

- Encrypt with `age` or `gpg` before transmission.
- Or extend the tool to emit Bitwarden's `encrypted_json` format (small change, not yet implemented).
- Delete the file securely once it has served its purpose.

---

## Troubleshooting

**`bw CLI not found on PATH`** — install the Bitwarden CLI (see Path A step 1). Restart the GUI / your shell after installing so the new PATH is picked up.

**`Invalid master password` when unlocking, but the password is correct** — your account may have a pending email-code 2FA challenge. Run `bw login` interactively in a terminal once to clear it; bwexport's API-key login flow won't trigger an email challenge afterward.

**Unlock succeeds but the collection list is empty** — the account may not be a member of the organization you specified, or the organization UUID is wrong. Re-check it from the web vault URL.

**`Multiple collections matched`** in the CLI — `--client` substring matched more than one collection. Use a more specific name or copy-paste the exact collection name.

**Build fails with `keyring.backends.Windows` not found in the bundled `.exe`** — rebuild with the explicit hidden-import flag (already in `build_windows.ps1`). If it still fails, delete `build/` and `dist/` and rebuild with `--clean`.

**Exported CSV doesn't import cleanly into another Bitwarden vault** — verify you're targeting the *organization* import format on the receiving end, not the personal-vault format. The two have slightly different column expectations.

---

## Roadmap

- **PDF output** for printable export documents (ReportLab on top of the same item-fetch logic).
- **Multi-collection batch export** — one CSV per selected collection in a single run.
- **Encrypted JSON output** as a safer alternative to plaintext CSV when both ends are Bitwarden.
- **Dry-run / preview mode** — list items in a collection without writing the CSV.

---

## License

MIT — see [`LICENSE`](LICENSE).
