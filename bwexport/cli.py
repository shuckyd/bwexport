"""Headless CLI: export a single Bitwarden organization collection as Bitwarden-compatible CSV.

Sibling to bwexport.gui. See bwexport.core for the security model.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from bwexport import core


def find_collection(session, org_id, query):
    cols = core.list_org_collections(session, org_id)
    matches = core.filter_collections(cols, query)
    exact = [c for c in matches if c["name"].lower() == query.lower()]
    if exact:
        return exact[0]
    if not matches:
        raise SystemExit(f"no collection matched '{query}'")
    if len(matches) == 1:
        return matches[0]
    sys.stderr.write("Multiple collections matched — choose one:\n")
    for i, c in enumerate(matches):
        sys.stderr.write(f"  [{i}] {c['name']}\n")
    return matches[int(input("index: "))]


def get_api_key(allow_keychain: bool):
    if allow_keychain:
        cid, csec = core.keyring_get_api_key()
        if cid and csec:
            return cid, csec

    sys.stderr.write(
        "Bitwarden API key not in OS credential store. Get one at: "
        "Web vault > Account settings > Security > Keys > View API key.\n"
    )
    cid = getpass.getpass("BW_CLIENTID: ").strip()
    csec = getpass.getpass("BW_CLIENTSECRET: ").strip()

    if allow_keychain:
        sys.stderr.write("Store this API key in the OS credential store for next time? [y/N] ")
        if input().strip().lower() == "y":
            core.keyring_set_api_key(cid, csec)
    return cid, csec


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server", required=True, help="Self-hosted Bitwarden URL (https://...)")
    p.add_argument("--org-id", required=True, help="Organization UUID")
    p.add_argument("--client", required=True, help="Collection name to export (substring match)")
    p.add_argument("--out", required=True, type=Path, help="Output CSV path")
    p.add_argument("--no-keychain", action="store_true",
                   help="Do not read or write the API key from the OS credential store")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        core.ensure_bw_installed()
        core.configure_server(args.server)
        client_id, client_secret = get_api_key(allow_keychain=not args.no_keychain)
        master = getpass.getpass("Bitwarden master password: ")

        with core.session_context(client_id, client_secret, master) as session:
            del master
            core.sync(session)
            col = find_collection(session, args.org_id, args.client)
            items = core.list_collection_items(session, args.org_id, col["id"])
            core.write_csv(items, col["name"], args.out)
    except core.BWError as e:
        raise SystemExit(str(e))

    sys.stderr.write(
        f"Exported {len(items)} item(s) from collection '{col['name']}' to {args.out}.\n"
        f"Reminder: this CSV contains plaintext passwords. Encrypt before transmission and "
        f"delete the file securely once it has served its purpose.\n"
    )


if __name__ == "__main__":
    main()
