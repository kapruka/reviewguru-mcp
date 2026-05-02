#!/usr/bin/env bash
# Publish the current `server.json` to the MCP Registry.
#
# Why this exists: `mcp-publisher login github` uses an OAuth device-flow
# whose JWT expires after 5 minutes — too short for any non-trivial
# release pipeline. Instead we exchange the project's GITHUB_TOKEN
# (PAT) for a registry JWT and save it in mcp-publisher's expected
# location, then call `publish`.
#
# Usage:  bash mcp/registry-publish.sh
#
# Prereqs:
#   - GITHUB_TOKEN in ../.env.local (or the environment)
#   - mcp-publisher binary on $PATH or at /tmp/mcp-publisher.exe
#   - server.json present in this directory
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${GITHUB_TOKEN:-}" ] && [ -f ../.env.local ]; then
  GITHUB_TOKEN=$(grep -E '^GITHUB_TOKEN=' ../.env.local | head -1 | cut -d= -f2-)
fi
: "${GITHUB_TOKEN:?GITHUB_TOKEN not set — paste it into .env.local or export it}"

PUB=$(command -v mcp-publisher || echo /tmp/mcp-publisher.exe)
[ -x "$PUB" ] || { echo "mcp-publisher binary not found"; exit 1; }

echo "==== exchanging GitHub PAT for registry JWT ===="
TOKEN=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"github_token\":\"$GITHUB_TOKEN\"}" \
  https://registry.modelcontextprotocol.io/v0/auth/github-at \
  | python -c 'import json,sys; print(json.load(sys.stdin)["registry_token"])')

mkdir -p "$HOME/.config/mcp-publisher"
cat > "$HOME/.config/mcp-publisher/token.json" <<EOF
{
  "method": "github-at",
  "registry": "https://registry.modelcontextprotocol.io",
  "token": "$TOKEN"
}
EOF

echo "==== publishing ===="
"$PUB" publish

echo ""
echo "==== verify ===="
NAME=$(python -c 'import json; print(json.load(open("server.json"))["name"])')
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=$NAME" \
  | python -c 'import json,sys; d=json.load(sys.stdin); s=d["servers"][0]["server"]; m=d["servers"][0]["_meta"]["io.modelcontextprotocol.registry/official"]; print(f"  {s[\"name\"]} {s[\"version\"]} status={m[\"status\"]}")'
