# Run from PowerShell: .\scripts\quickstart.ps1
$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is required.'
}
docker compose version | Out-Null

if (-not (Test-Path 'policy.yaml')) {
    Copy-Item 'policy.example.yaml' 'policy.yaml'
    Write-Host 'Created policy.yaml from policy.example.yaml'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    function New-AgentGateSecret { -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }) }
    $content = Get-Content '.env' -Raw
    $content = $content.Replace('replace-with-a-long-random-agent-token', (New-AgentGateSecret))
    $content = $content.Replace('replace-with-a-separate-long-random-reviewer-token', (New-AgentGateSecret))
    $content = $content.Replace('replace-with-a-random-webhook-secret', (New-AgentGateSecret))
    Set-Content '.env' $content -NoNewline
    Write-Host 'Created .env with separate random local tokens. Keep this file private.'
}

New-Item -ItemType Directory -Force -Path 'secrets' | Out-Null
Write-Host 'Starting AgentGate at http://localhost:8080'
Write-Host 'GitHub execution remains fail-closed until a GitHub App is configured.'
docker compose up --build
