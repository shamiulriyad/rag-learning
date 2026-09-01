# Applies every pending file in supabase/migrations/ to the remote database.
# Usage:  ./supabase/migrate.ps1
#
# Reads supabase/.env:
#   SUPABASE_DB_URL       - connection string from the dashboard "Connect" dialog,
#                           keeping the literal [YOUR-PASSWORD] placeholder
#   SUPABASE_DB_PASSWORD  - raw DB password (this script percent-encodes it)
#
# The Supabase CLI tracks applied migrations in supabase_migrations.schema_migrations,
# so re-running only applies what is new.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $here
$envFile = Join-Path $here '.env'

if (-not (Test-Path $envFile)) {
    Write-Error "supabase/.env not found. Copy supabase/.env.example to supabase/.env."
}

function Get-EnvVar($name) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$name\s*=\s*(.*?)\s*$") {
            return $Matches[1].Trim('"').Trim("'")
        }
    }
    return $null
}

$dbUrl = Get-EnvVar 'SUPABASE_DB_URL'
$dbPass = Get-EnvVar 'SUPABASE_DB_PASSWORD'

if ([string]::IsNullOrWhiteSpace($dbUrl)) {
    Write-Error "SUPABASE_DB_URL is empty in supabase/.env"
}
if ($dbUrl -match 'REGION') {
    Write-Error "SUPABASE_DB_URL still contains 'REGION'. Copy the real URI from the dashboard 'Connect' dialog."
}
if ($dbUrl -match '\[YOUR-PASSWORD\]') {
    if ([string]::IsNullOrWhiteSpace($dbPass)) {
        Write-Error "Set SUPABASE_DB_PASSWORD in supabase/.env (raw password, no encoding)."
    }
    $enc = [uri]::EscapeDataString($dbPass)
    $dbUrl = $dbUrl -replace '\[YOUR-PASSWORD\]', $enc
}

Push-Location $repoRoot
try {
    npx --yes supabase@latest db push --db-url $dbUrl
}
finally {
    Pop-Location
}
