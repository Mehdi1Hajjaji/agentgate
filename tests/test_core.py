from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentgate.policy import Policy
from agentgate.store import Store


class AgentGateCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/"gate.sqlite")

    def tearDown(self): self.temp.cleanup()

    def request(self):
        return self.store.create_request("agent-a","acme/example-repository","github.create_issue",{"title":"Bounded change","body":"A reviewed change."},"Need a tracked issue.","i"*32,"1")[0]

    def test_requester_cannot_self_approve(self):
        row=self.request()
        with self.assertRaises(PermissionError): self.store.decide(row["id"],"agent-a","looks good",True)

    def test_idempotency_returns_original_request(self):
        first=self.request(); second,created=self.store.create_request("agent-a","acme/example-repository","github.create_issue",{"title":"changed","body":"changed"},"changed","i"*32,"1")
        self.assertFalse(created); self.assertEqual(first["id"],second["id"])

    def test_capability_is_single_use_and_receipt_binds_external_result(self):
        row=self.request(); approved=self.store.decide(row["id"],"reviewer-b","bounded approval",True)
        reserved=self.store.reserve_execution(approved["id"])
        receipt=self.store.record_receipt(reserved["id"],{"url":"https://github.com/acme/example-repository/issues/1","number":1})
        self.assertTrue(receipt["receipt_hash"])
        with self.assertRaises(PermissionError): self.store.reserve_execution(approved["id"])

    def test_default_deny_and_strict_payload(self):
        policy=Policy({"version":"1","default":"deny","repositories":{"acme/example-repository":{"actions":{"github.create_issue":{"approval":"required","max_title_length":8,"max_body_length":30}}}}})
        self.assertFalse(policy.evaluate("unknown/repo","github.create_issue",{"title":"x","body":"x"}).allowed)
        self.assertFalse(policy.evaluate("acme/example-repository","github.create_issue",{"title":"too long title","body":"x"}).allowed)
        self.assertTrue(policy.evaluate("acme/example-repository","github.create_issue",{"title":"ok","body":"fine"}).allowed)

    def test_likely_credential_payload_is_rejected_before_review(self):
        policy=Policy({"version":"1","default":"deny","repositories":{"acme/example-repository":{"actions":{"github.create_issue":{"approval":"required"}}}}})
        outcome=policy.evaluate("acme/example-repository","github.create_issue",{"title":"ok","body":"github_pat_abcdefghijklmnopqrstuvwxyz0123456789"})
        self.assertFalse(outcome.allowed); self.assertEqual(outcome.reason,"payload_contains_likely_secret")


if __name__=="__main__": unittest.main()
