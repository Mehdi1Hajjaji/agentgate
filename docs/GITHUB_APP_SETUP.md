# GitHub App setup

Create a dedicated GitHub App and install it only on the repositories governed
by ChangeWarden. Do not use a personal access token.

Minimum permissions depend on enabled actions:

| ChangeWarden action | GitHub App permission |
| --- | --- |
| create issue / comment | Issues: Read and write |
| create pull request / request review | Pull requests: Read and write |

Use **Contents: Read-only** unless you later add a separately reviewed branch
creation feature. ChangeWarden v0.1 never writes repository contents.

Set the webhook endpoint to `https://YOUR_GATE/github/webhook`, enable the
events you need, and place the webhook secret only in `CHANGEWARDEN_GITHUB_WEBHOOK_SECRET`.
Place the downloaded private key at the configured secret path; never commit it.
