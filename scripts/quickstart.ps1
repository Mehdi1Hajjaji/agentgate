# Run from PowerShell: .\scripts\quickstart.ps1
$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is required.'
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Compose is unavailable.'
}
docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is installed but its daemon is not running.'
}

if (-not (Test-Path 'policy.yaml')) {
    Copy-Item 'policy.example.yaml' 'policy.yaml'
    Write-Host 'Created policy.yaml from policy.example.yaml'
}

if ((Test-Path '.env') -and (Select-String -Path '.env' -Pattern '^AGENTGATE_' -Quiet)) {
    Move-Item '.env' '.env.agentgate-legacy'
    Write-Host 'Preserved legacy AgentGate .env as .env.agentgate-legacy; generating ChangeWarden configuration.'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    function New-ChangeWardenSecret { -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }) }
    $content = Get-Content '.env' -Raw
    $content = $content.Replace('replace-with-a-long-random-agent-token', (New-ChangeWardenSecret))
    $content = $content.Replace('replace-with-a-separate-long-random-reviewer-token', (New-ChangeWardenSecret))
    $content = $content.Replace('replace-with-a-random-webhook-secret', (New-ChangeWardenSecret))
    Set-Content '.env' $content -NoNewline
    Write-Host 'Created .env with separate random local tokens. Keep this file private.'
}

New-Item -ItemType Directory -Force -Path 'secrets' | Out-Null
Write-Host 'Starting ChangeWarden at http://localhost:8080'
Write-Host 'GitHub execution remains fail-closed until a GitHub App is configured.'
docker compose up --build
