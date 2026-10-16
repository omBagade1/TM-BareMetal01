import hashlib
import json
import sqlite3
import threading
import os
from pathlib import Path

from .config import utcnow

GENESIS_HASH = "agentguard-genesis-v1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    decision TEXT,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class Audit:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.anchor_path = db_path.with_suffix(db_path.suffix + '.head')
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(SCHEMA)
            columns = {r[1] for r in self._conn.execute('PRAGMA table_info(audit_events)')}
            migrated = 'version' not in columns
            if migrated:
                self._conn.execute('ALTER TABLE audit_events ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
            self._conn.commit()
            if migrated:
                self._write_anchor()

    def _head(self):
        row = self._conn.execute('SELECT id, event_hash FROM audit_events ORDER BY id DESC LIMIT 1').fetchone()
        return {'id': row['id'] if row else 0, 'hash': row['event_hash'] if row else GENESIS_HASH}

    def _write_anchor(self):
        temporary = self.anchor_path.with_suffix(self.anchor_path.suffix + '.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(canon(self._head()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.anchor_path)

    @staticmethod
    def _digest(r):
        if r['version'] == 1:
            text = r['prev_hash'] + r['payload']
        elif r['version'] == 2:
            text = canon({key: r[key] for key in ('version', 'id', 'ts', 'event_type', 'decision', 'prev_hash', 'payload')})
        else:
            return None
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["event_hash"] if row else GENESIS_HASH

    def append(self, event_type: str, payload: dict, decision: str | None = None) -> dict:
        body = canon(payload)
        ts = utcnow()
        with self._lock:
            if not self.verify()['verified']:
                raise RuntimeError('Audit integrity failure; refusing to append')
            prev = self.last_hash()
            cur = self._conn.execute(
                "INSERT INTO audit_events (ts, event_type, decision, prev_hash, event_hash, payload, version) "
                "VALUES (?,?,?,?,?,?,2)",
                (ts, event_type, decision, prev, '', body),
            )
            rid = cur.lastrowid
            digest = self._digest(dict(version=2, id=rid, ts=ts, event_type=event_type,
                                       decision=decision, prev_hash=prev, payload=body))
            self._conn.execute('UPDATE audit_events SET event_hash=? WHERE id=?', (digest, rid))
            self._conn.commit()
            self._write_anchor()
        return {
            "id": rid,
            "ts": ts,
            "event_type": event_type,
            "decision": decision,
            "prev_hash": prev,
            "event_hash": digest,
            "payload": payload,
        }

    def clear(self) -> dict:
        with self._lock:
            with self._conn:
                count, last_id = self._conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM audit_events"
                ).fetchone()
                self._conn.execute("DELETE FROM audit_events")
            self._write_anchor()
        # Retain the sequence so old links can never point at a new event.
        return {"cleared": count, "through_id": last_id}

    def tail(self, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts, event_type, decision, prev_hash, event_hash, payload "
            "FROM audit_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in reversed(rows):
            try:
                payload = json.loads(r["payload"])
            except Exception:
                payload = {"raw": r["payload"]}
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "event_type": r["event_type"],
                    "decision": r["decision"],
                    "prev_hash": r["prev_hash"],
                    "event_hash": r["event_hash"],
                    "payload": payload,
                }
            )
        return out

    def verify(self) -> dict:
        with self._lock:
            return self._verify()

    def _verify(self) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM audit_events ORDER BY id ASC"
        ).fetchall()
        expected_prev = GENESIS_HASH
        tampered = []
        for r in rows:
            digest = self._digest(r)
            if digest != r["event_hash"] or r["prev_hash"] != expected_prev:
                tampered.append(r["id"])
                break
            expected_prev = r["event_hash"]
        try:
            anchor_matches = json.loads(self.anchor_path.read_text(encoding='utf-8')) == self._head()
        except (OSError, ValueError):
            anchor_matches = False
        return {
            "total": len(rows),
            "genesis": GENESIS_HASH,
            "head": expected_prev,
            "tampered_ids": tampered,
            "verified": not tampered and anchor_matches,
            "anchor_matches": anchor_matches,
            "legacy_records": sum(r['version'] == 1 for r in rows),
            "anchor_scope": "local sidecar; independently retain a checkpoint to detect full rollback",
        }
