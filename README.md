# AgentGate

**Governed GitHub actions for AI coding agents.**

AgentGate is a narrow execution boundary for coding agents such as Codex, Claude, Cursor, and custom automation. The Agent asks for a typed GitHub action; AgentGate evaluates a default-deny policy, requires an independent human decision, executes through a GitHub App whose credentials never enter the Agent, then stores a hash-linked receipt that includes the external result.

It is deliberately not a generic proxy, a raw GitHub API relay, or a claim to solve AI alignment.

```text
Agent / MCP client -> AgentGate policy -> independent approval
                                         -> one-time internal capability
                                         -> GitHub App execution -> receipt
```

## What is governed

`github.create_issue`, `github.create_pull_request`, `github.create_comment`, and `github.request_review` are the only accepted actions. Every repository and action must occur in `policy.yaml`; the default is deny.

AgentGate v0.1 does **not** merge pull requests, modify repository contents, touch Actions secrets, modify settings, or manage collaborators.

## One-command local start

With Docker Desktop running, use one command from the repository root:

```bash
bash scripts/quickstart.sh
```

On PowerShell:

```powershell
.\scripts\quickstart.ps1
```

The script creates a local `policy.yaml`, secret `.env`, and `secrets/` folder
only when they do not already exist, then starts AgentGate at
`http://localhost:8080`. It never generates or stores a GitHub credential.
You can use the approval flow locally; GitHub execution remains deliberately
blocked until the App configuration described below exists.

## Manual start

```bash
cp policy.example.yaml policy.yaml
cp .env.example .env
# Set two distinct long random values in .env:
# AGENTGATE_AGENT_TOKEN and AGENTGATE_ADMIN_TOKEN
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python -m agentgate.app
```

The service runs at `http://127.0.0.1:8080`. It refuses to start without separate Agent and reviewer tokens. It can accept requests before GitHub App credentials are configured; execution then fails closed with `github_app_not_configured`.

For Docker, copy `policy.example.yaml` to `policy.yaml`, create `.env`, place the GitHub App PEM in `secrets/github_app_private_key.pem`, then run `docker compose up --build`.

## 30-second governed flow

Ask for an Issue using the Agent token. The Agent gets no GitHub credential.

```bash
curl -X POST http://127.0.0.1:8080/v1/actions \
  -H "Authorization: Bearer $AGENTGATE_AGENT_TOKEN" \
  -H "X-AgentGate-Actor: codex-demo" -H 'Content-Type: application/json' \
  -d '{
    "repository":"acme/example-repository",
    "action":"github.create_issue",
    "payload":{"title":"Review deployment plan","body":"Bounded demo issue."},
    "reason":"Track the approved deployment review.",
    "idempotency_key":"demo-issue-2026-0001"
  }'
```

Open the returned `review_url`, enter a reviewer identity different from `codex-demo`, provide the administrator token, and approve or deny. Approval does not execute. The requesting Agent then makes one fresh execution request:

```bash
curl -X POST http://127.0.0.1:8080/v1/requests/REQUEST_ID/execute \
  -H "Authorization: Bearer $AGENTGATE_AGENT_TOKEN" \
  -H "X-AgentGate-Actor: codex-demo"
```

The same request cannot execute twice. A successful response includes the external GitHub URL and receipt hash. Verify local evidence with `python scripts/verify_receipts.py`.

## MCP setup

Run `mcp/server.py` as a stdio MCP server with `AGENTGATE_URL`, `AGENTGATE_AGENT_TOKEN`, and `AGENTGATE_ACTOR_ID`. It exposes exactly one tool: `governed_github_action`.

Do not also expose a direct GitHub write tool or GitHub token to the same Agent; doing so creates a bypass outside AgentGate's security boundary.

## Security boundary

- GitHub uses an App installation token minted inside AgentGate, not a PAT.
- A policy is reloaded and checked immediately before the GitHub call.
- Common credential-shaped values are rejected before they can reach the review inbox or GitHub; this is a guardrail, not a substitute for DLP.
- Approval has requester/reviewer separation.
- `approved -> executing` is an atomic SQLite transition.
- Receipts are linked by SHA-256 and bind the request, capability, external reference, timestamp, and preceding receipt.

Read [the threat model](docs/THREAT_MODEL.md) and [GitHub App setup](docs/GITHUB_APP_SETUP.md) before any deployment.

## Development checks

```bash
export PYTHONPATH=src
python -m unittest discover -s tests -v
```

## License

Apache-2.0. See [LICENSE](LICENSE).
