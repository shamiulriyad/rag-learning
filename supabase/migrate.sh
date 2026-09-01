#!/usr/bin/env bash
# Applies every pending file in supabase/migrations/ to the remote database.
# Usage:  ./supabase/migrate.sh
#
# Reads supabase/.env:
#   SUPABASE_DB_URL       - connection string from the dashboard "Connect" dialog,
#                           keeping the literal [YOUR-PASSWORD] placeholder
#   SUPABASE_DB_PASSWORD  - raw DB password (this script percent-encodes it)
#
# The Supabase CLI tracks applied migrations in supabase_migrations.schema_migrations,
# so re-running only applies what is new.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$here")"
env_file="$here/.env"

[ -f "$env_file" ] || { echo "supabase/.env not found. Copy supabase/.env.example to supabase/.env." >&2; exit 1; }

get_var() { grep -E "^\s*$1\s*=" "$env_file" | head -n1 | cut -d= -f2- | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//'; }

db_url="$(get_var SUPABASE_DB_URL)"
db_pass="$(get_var SUPABASE_DB_PASSWORD)"

[ -n "$db_url" ] || { echo "SUPABASE_DB_URL is empty in supabase/.env" >&2; exit 1; }

if echo "$db_url" | grep -q 'REGION'; then
  echo "SUPABASE_DB_URL still contains 'REGION'. Copy the real URI from the dashboard 'Connect' dialog." >&2
  exit 1
fi

if echo "$db_url" | grep -q '\[YOUR-PASSWORD\]'; then
  [ -n "$db_pass" ] || { echo "Set SUPABASE_DB_PASSWORD in supabase/.env (raw password, no encoding)." >&2; exit 1; }
  enc="$(python -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$db_pass")"
  db_url="${db_url/\[YOUR-PASSWORD\]/$enc}"
fi

cd "$repo_root"
npx --yes supabase@latest db push --db-url "$db_url"
