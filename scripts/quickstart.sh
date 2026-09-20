#!/usr/bin/env bash
# Run AgentGate locally without manually creating policy or random credentials.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "A running Docker Desktop daemon with Docker Compose is required."
  exit 1
fi

if [ ! -f policy.yaml ]; then
  cp policy.example.yaml policy.yaml
  echo "Created policy.yaml from policy.example.yaml"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  agent_token="$(openssl rand -hex 32)"
  admin_token="$(openssl rand -hex 32)"
  webhook_secret="$(openssl rand -hex 32)"
  sed -i "s|replace-with-a-long-random-agent-token|${agent_token}|; s|replace-with-a-separate-long-random-reviewer-token|${admin_token}|; s|replace-with-a-random-webhook-secret|${webhook_secret}|" .env
  chmod 600 .env
  echo "Created .env with distinct random local tokens. Keep this file private."
fi

mkdir -p secrets
echo "Starting AgentGate at http://localhost:8080"
echo "GitHub App is optional for the local approval demo; external execution remains fail-closed until configured."
docker compose up --build
