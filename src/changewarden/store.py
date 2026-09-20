from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS action_requests (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                requester_id TEXT NOT NULL,
                repository TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending_approval','approved','denied','executing','executed','failed')),
                request_reason TEXT NOT NULL,
                approver_id TEXT NULL,
                approval_reason TEXT NULL,
                approval_at TEXT NULL,
                capability_id TEXT NULL UNIQUE,
                execution_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                action_request_id TEXT NOT NULL UNIQUE REFERENCES action_requests(id),
                capability_id TEXT NOT NULL UNIQUE,
                external_reference_json TEXT NOT NULL,
                accepted_at TEXT NOT NULL,
                previous_hash TEXT NULL,
                receipt_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS github_webhook_events (
                delivery_id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            """)
            conn.commit()

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def create_request(self, requester: str, repository: str, action: str, payload: dict[str, Any], reason: str, idempotency_key: str, policy_version: str) -> tuple[dict[str, Any], bool]:
        if len(idempotency_key) < 16 or len(idempotency_key) > 200:
            raise ValueError("idempotency_key must be 16-200 characters")
        now = utc_now()
        request_id = "req_" + secrets.token_hex(16)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM action_requests WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                conn.commit()
                return self._public(existing), False
            conn.execute("""INSERT INTO action_requests
                (id,idempotency_key,requester_id,repository,action,payload_json,policy_version,status,request_reason,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,'pending_approval',?,?,?)""",
                (request_id,idempotency_key,requester,repository,action,json.dumps(payload,sort_keys=True,separators=(",",":")),policy_version,reason,now,now))
            row = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            conn.commit()
            return self._public(row), True

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            return self._public(row) if row else None

    def list_pending(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM action_requests WHERE status = 'pending_approval' ORDER BY created_at ASC").fetchall()
            return [self._public(row) for row in rows]

    def decide(self, request_id: str, approver: str, approval_reason: str, approve: bool) -> dict[str, Any]:
        if not approver.strip() or not approval_reason.strip():
            raise ValueError("approver identity and decision reason are required")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            if not row:
                raise LookupError("request_not_found")
            if row["status"] != "pending_approval":
                raise ValueError("request_is_not_pending")
            if secrets.compare_digest(row["requester_id"], approver):
                raise PermissionError("self_approval_forbidden")
            status = "approved" if approve else "denied"
            capability = "cap_" + secrets.token_hex(16) if approve else None
            now = utc_now()
            conn.execute("""UPDATE action_requests SET status=?, approver_id=?, approval_reason=?, approval_at=?, capability_id=?, updated_at=? WHERE id=?""",
                (status,approver,approval_reason,now,capability,now,request_id))
            updated = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            conn.commit()
            return self._public(updated)

    def reserve_execution(self, request_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            if not row:
                raise LookupError("request_not_found")
            if row["status"] != "approved":
                raise PermissionError("capability_not_active_or_already_used")
            updated = conn.execute("UPDATE action_requests SET status='executing', updated_at=? WHERE id=? AND status='approved'", (utc_now(), request_id))
            if updated.rowcount != 1:
                raise PermissionError("capability_not_active_or_already_used")
            result = conn.execute("SELECT * FROM action_requests WHERE id = ?", (request_id,)).fetchone()
            conn.commit()
            return self._public(result)

    def fail_execution(self, request_id: str, reason: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE action_requests SET status='failed', execution_error=?, updated_at=? WHERE id=? AND status='executing'", (reason[:500],utc_now(),request_id))
            conn.commit()

    def record_receipt(self, request_id: str, external_reference: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            request = conn.execute("SELECT * FROM action_requests WHERE id=? AND status='executing'", (request_id,)).fetchone()
            if not request:
                raise ValueError("execution_not_reserved")
            prior = conn.execute("SELECT receipt_hash FROM receipts ORDER BY accepted_at DESC, rowid DESC LIMIT 1").fetchone()
            previous = prior["receipt_hash"] if prior else None
            accepted_at = utc_now()
            normalized = json.dumps(external_reference,sort_keys=True,separators=(",",":"))
            material = "|".join([previous or "",request_id,request["capability_id"],normalized,accepted_at])
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            receipt_id = "rcpt_" + secrets.token_hex(16)
            conn.execute("INSERT INTO receipts (id,action_request_id,capability_id,external_reference_json,accepted_at,previous_hash,receipt_hash) VALUES (?,?,?,?,?,?,?)", (receipt_id,request_id,request["capability_id"],normalized,accepted_at,previous,digest))
            conn.execute("UPDATE action_requests SET status='executed',updated_at=? WHERE id=?", (accepted_at,request_id))
            conn.commit()
            return {"id":receipt_id,"action_request_id":request_id,"accepted_at":accepted_at,"previous_hash":previous,"receipt_hash":digest,"external_reference":external_reference}

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if not row:
                return None
            value=dict(row); value["external_reference"]=json.loads(value.pop("external_reference_json")); return value

    def record_webhook(self, delivery_id: str, event_name: str, raw: bytes) -> bool:
        with self.connection() as conn:
            try:
                conn.execute("INSERT INTO github_webhook_events VALUES (?,?,?,?)", (delivery_id,event_name,hashlib.sha256(raw).hexdigest(),utc_now()))
                conn.commit(); return True
            except sqlite3.IntegrityError:
                return False
