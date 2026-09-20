# ChangeWarden

**Governed GitHub changes for AI coding agents.**

ChangeWarden is a narrow execution boundary for Codex, Claude, Cursor, and custom coding agents. An Agent requests one typed GitHub change; ChangeWarden applies a default-deny policy, obtains an independent human decision when required, executes with a GitHub App credential that never enters the Agent, and records a receipt bound to GitHub's actual response.

```text
Agent / MCP client -> policy -> independent approval -> one-time execution
                                                        -> GitHub App -> receipt
```

It is not a generic GitHub proxy, a raw REST relay, or a solution to model alignment. Its claim is narrower: a configured GitHub change that crosses this Gate cannot execute without the policy and approval path recorded for it.

## Scope

Only four typed actions exist:

- `github.create_issue`
- `github.create_pull_request` from an existing branch
- `github.create_comment`
- `github.request_review`

Every repository and action must be explicitly listed in `policy.yaml`; the default is deny. ChangeWarden does not merge pull requests, write repository contents, alter secrets or settings, manage collaborators, or accept arbitrary GitHub URLs, methods, or headers.

## One-command local start

With Docker Desktop running, start from the repository root:

```bash
bash scripts/quickstart.sh
```

On PowerShell:

```powershell
.\scripts\quickstart.ps1
```

The script creates a local `policy.yaml`, private `.env`, and `secrets/` directory only if missing, then starts `http://localhost:8080`. It never creates or stores a GitHub credential. The review flow works locally; external GitHub execution fails closed until the GitHub App configuration exists.

## Governed flow

An Agent submits a bounded action. It receives a review URL, not a GitHub token.

```bash
curl -X POST http://127.0.0.1:8080/v1/actions \
  -H "Authorization: Bearer $CHANGEWARDEN_AGENT_TOKEN" \
  -H "X-ChangeWarden-Actor: codex-demo" \
  -H 'Content-Type: application/json' \
  -d '{
    "repository":"acme/example-repository",
    "action":"github.create_issue",
    "payload":{"title":"Review deployment plan","body":"Bounded demo issue."},
    "reason":"Track the approved deployment review.",
    "idempotency_key":"demo-issue-2026-0001"
  }'
```

Open the returned `review_url`. A reviewer whose identity differs from the requester approves or denies with the separate reviewer token.

`auto_execute_on_approval: true` is available per action in policy and is enabled in the example policy. With it, ChangeWarden rechecks the current policy and calls GitHub itself immediately after approval. The Agent never gets a second execution power and does not need polling to cause the change.

Set `auto_execute_on_approval: false` when an operator wants an explicit, separate dispatch step. In both modes, the `approved -> executing` transition is atomic and cannot be used twice.

Successful execution returns GitHub's external URL plus a hash-linked receipt. Verify local evidence with:

```bash
python scripts/verify_receipts.py
```

## MCP setup

The stdio MCP adapter exposes two narrow tools:

- `governed_github_change` requests a typed change.
- `get_governed_change_status` reads its decision and receipt state.

Example for Claude Desktop or another stdio-compatible MCP client:

```json
{
  "mcpServers": {
    "changewarden": {
      "command": "python",
      "args": ["/absolute/path/to/changewarden/mcp/server.py"],
      "env": {
        "CHANGEWARDEN_URL": "http://127.0.0.1:8080",
        "CHANGEWARDEN_AGENT_TOKEN": "agent-token-only",
        "CHANGEWARDEN_ACTOR_ID": "claude-coding-agent"
      }
    }
  }
}
```

Do not expose direct GitHub write tools or a GitHub token to the same Agent. Either creates a bypass outside ChangeWarden's security boundary.

## Security properties

- GitHub uses an App installation token minted inside ChangeWarden, never a personal access token held by the Agent.
- Policy is reloaded and evaluated immediately before any external call.
- Requester and reviewer must differ; self-approval is rejected.
- Idempotency keys deduplicate an intent; an atomic state transition prevents a capability from executing twice.
- Common credential-shaped input is rejected before it reaches the review inbox or GitHub. This is a guardrail, not general DLP.
- Each accepted outcome appends a SHA-256 receipt binding request, capability, external reference, timestamp, and previous receipt hash.

Read [the threat model](docs/THREAT_MODEL.md) and [GitHub App setup](docs/GITHUB_APP_SETUP.md) before deployment.

## Development checks

```bash
export PYTHONPATH=src
python -m unittest discover -s tests -v
```

## License

Apache-2.0. See [LICENSE](LICENSE).
