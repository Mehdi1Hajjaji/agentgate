from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import yaml


ALLOWED_ACTIONS = {
    "github.create_issue",
    "github.create_pull_request",
    "github.create_comment",
    "github.request_review",
}

# A small fail-closed guard for the most common accidental credential shapes.
# This is not marketed as a general DLP engine; unknown secret formats still
# require operational controls and human review.
LIKELY_SECRET = re.compile(
    r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    constraints: dict[str, Any]


class Policy:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @classmethod
    def load(cls, path: Path) -> "Policy":
        if not path.exists():
            raise ValueError(f"Policy file does not exist: {path}")
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or parsed.get("default") != "deny":
            raise ValueError("Policy must be a mapping with default: deny")
        return cls(parsed)

    def evaluate(self, repository: str, action: str, payload: dict[str, Any]) -> PolicyDecision:
        if action not in ALLOWED_ACTIONS:
            return PolicyDecision(False, True, "action_not_allowlisted", {})
        repo = self.raw.get("repositories", {}).get(repository)
        if not isinstance(repo, dict):
            return PolicyDecision(False, True, "repository_not_allowlisted", {})
        rule = repo.get("actions", {}).get(action)
        if not isinstance(rule, dict):
            return PolicyDecision(False, True, "action_not_permitted_for_repository", {})
        if rule.get("approval") != "required":
            return PolicyDecision(False, True, "approval_must_be_required", {})
        if LIKELY_SECRET.search(str(payload)):
            return PolicyDecision(False, True, "payload_contains_likely_secret", {})
        valid, reason = self._validate_payload(action, payload, rule)
        return PolicyDecision(valid, True, "approval_required" if valid else reason, rule)

    @staticmethod
    def _text(value: object, limit: int) -> bool:
        return isinstance(value, str) and 1 <= len(value.strip()) <= limit

    def _validate_payload(self, action: str, payload: dict[str, Any], rule: dict[str, Any]) -> tuple[bool, str]:
        if action == "github.create_issue":
            if not self._text(payload.get("title"), int(rule.get("max_title_length", 160))):
                return False, "invalid_issue_title"
            if not self._text(payload.get("body"), int(rule.get("max_body_length", 10000))):
                return False, "invalid_issue_body"
        elif action == "github.create_pull_request":
            if not self._text(payload.get("title"), int(rule.get("max_title_length", 160))):
                return False, "invalid_pull_request_title"
            if not self._text(payload.get("head"), 255):
                return False, "invalid_pull_request_head"
            base = payload.get("base")
            allowed = rule.get("allowed_base_branches", [])
            if not isinstance(base, str) or base not in allowed:
                return False, "base_branch_not_allowed"
        elif action == "github.create_comment":
            if not isinstance(payload.get("issue_number"), int) or payload["issue_number"] < 1:
                return False, "invalid_issue_number"
            if not self._text(payload.get("body"), int(rule.get("max_body_length", 10000))):
                return False, "invalid_comment_body"
        elif action == "github.request_review":
            if not isinstance(payload.get("pull_number"), int) or payload["pull_number"] < 1:
                return False, "invalid_pull_number"
            reviewers = payload.get("reviewers")
            if not isinstance(reviewers, list) or not reviewers or len(reviewers) > 10 or not all(self._text(v, 39) for v in reviewers):
                return False, "invalid_reviewers"
        return True, "valid"
