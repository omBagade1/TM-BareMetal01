"""Read-only audit/checkpoint inspection. No migration or anchor repair."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from app.audit import Audit, GENESIS_HASH


def verify(path, checkpoint=None):
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute('SELECT * FROM audit_events ORDER BY id').fetchall()
        previous, failures = GENESIS_HASH, []
        for row in rows:
            record = dict(row)
            record.setdefault('version', 1)
            if record['prev_hash'] != previous or Audit._digest(record) != record['event_hash']:
                failures.append(record['id'])
            previous = record['event_hash']
        head = {'id': rows[-1]['id'] if rows else 0, 'hash': previous}
        local = json.loads(path.with_suffix(path.suffix + '.head').read_text(encoding='utf-8'))
        checkpoint_ok = None
        if checkpoint:
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            checkpoint_ok = any(row['id'] == saved['id'] and row['event_hash'] == saved['hash'] for row in rows)
        return {'verified': not failures and local == head and checkpoint_ok is not False,
                'head': head, 'tampered_ids': failures, 'local_anchor_matches': local == head,
                'external_checkpoint_matches': checkpoint_ok}
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.database, args.checkpoint)
    except Exception as exc:
        result = {'verified': False, 'error': str(exc)}
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['verified'] else 1)
