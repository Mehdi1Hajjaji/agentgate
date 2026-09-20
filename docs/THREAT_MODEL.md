# ChangeWarden threat model

## Claim

For GitHub actions routed through ChangeWarden, an Agent cannot cause a configured
write unless the repository/action/payload satisfy policy, a distinct reviewer
approves the request, and the Gate consumes one internal capability exactly
once before calling GitHub.

## Defended paths

- Default deny for unknown repositories and actions.
- Typed action payloads; no raw GitHub URL, method, or arbitrary headers.
- Separate requester and reviewer identities; self-approval is rejected.
- Idempotency keys deduplicate the same intent.
- Atomic `approved -> executing` transition prevents two successful dispatches.
- GitHub App private key and installation token remain in the Gate process.
- HMAC-verifiable GitHub webhooks are deduplicated by delivery ID.
- Every successful external call appends a hash-linked receipt.

## Non-claims

- It does not protect a host whose operating system, ChangeWarden administrator
  token, or GitHub App private key has been compromised.
- It does not prevent an Agent from using an unrelated GitHub credential or
  network route outside ChangeWarden. Deploy agents without GitHub credentials and
  without direct GitHub tooling if this boundary is required.
- A local hash chain is tamper-evident, not a globally immutable ledger.
- It does not judge whether a human-approved code change is correct or safe.
