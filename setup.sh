#!/bin/bash
# Store a Yahoo app password in the macOS Keychain and register the account.
set -euo pipefail
CONFIG_DIR="$HOME/.yahoo-mail"
CONFIG="$CONFIG_DIR/accounts.json"
mkdir -p "$CONFIG_DIR"; chmod 700 "$CONFIG_DIR"

read -rp "Account key (e.g. personal or work): " KEY
read -rp "Yahoo email address: " EMAIL
SVC="yahoo-mail-$KEY"
# A bare -w at the end makes security prompt for the password itself (hidden),
# so it never sits in a process's argv where a process listing could see it.
echo "Enter the Yahoo app password when security prompts for it (input hidden)."
/usr/bin/security add-generic-password -U -s "$SVC" -a "$EMAIL" -w
echo "Stored in Keychain under service '$SVC'."

python3 - "$CONFIG" "$KEY" "$EMAIL" "$SVC" <<'PY'
import json, sys
cfg, key, email, svc = sys.argv[1:5]
try:
    with open(cfg) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {"accounts": {}, "default": key}
data.setdefault("accounts", {})[key] = {"email": email, "keychain_service": svc}
data.setdefault("default", key)
with open(cfg, "w") as f:
    json.dump(data, f, indent=2)
print("Wrote", cfg)
PY
chmod 600 "$CONFIG"
echo "Done. Verify with the yahoo_check_auth MCP tool."
