import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import main
from app.audit import Audit
from app.policy import PolicyEngine


class ContentGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_read_is_blocked_audited_and_broadcast(self):
        fixture = Path(__file__).resolve().parents[1] / 'workspace/ps01-tests/attacks/02-indirect-injection/input/vendor-note.txt'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'vendor-note.txt').write_bytes(fixture.read_bytes())
            policy = PolicyEngine(root, root)
            policy.set_policy({'default_action': 'allow', 'rules': [{'action': 'allow'}]})
            audit = Audit(root / 'audit.db')
            try:
                with patch.object(main, 'policy', policy), patch.object(main, 'audit', audit), \
                     patch.object(main.config, 'load_secret', return_value='test'), \
                     patch.object(main, 'broadcast', AsyncMock()) as broadcast:
                    result = await main.internal_hook_evaluate(main.HookEvaluate(secret='test', toolCall={
                        'name': 'view_file', 'args': {'AbsolutePath': str(root / 'vendor-note.txt')}}))
                self.assertEqual(result['decision'], 'block')
                self.assertEqual(result['rule_id'], '__content_inspection')
                self.assertIn('suspected indirect prompt injection', result['reason'])
                row = audit.tail()[0]
                self.assertEqual(row['decision'], 'block')
                self.assertEqual(row['payload']['reason'], result['reason'])
                broadcast.assert_awaited_once_with({'type': 'action_issue', 'data': row})
                self.assertTrue(audit.verify()['verified'])
                for tool, args in [
                    ('read_file', {'path': 'vendor-note.txt'}),
                    ('run_command', {'CommandLine': 'Get-Content -Raw -LiteralPath "vendor-note.txt"', 'Cwd': str(root)})
                ]:
                    self.assertEqual(policy.evaluate(tool, args)[0], 'block')
            finally:
                audit._conn.close()

    async def test_normal_text_still_reviewable_and_size_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = PolicyEngine(root, root)
            note = root / 'note.txt'
            for text in ('Vendor update: delivery remains on schedule.',
                         'Read ../notes.txt for documentation. https://example.com is the vendor website.'):
                note.write_text(text)
                self.assertEqual(policy.evaluate('view_file', {'path': 'note.txt'})[0], 'ask')
            note.write_bytes(b'x' * (65536 + 1))
            decision, reason, _ = policy.evaluate('read_file', {'path': 'note.txt'})
            self.assertEqual(decision, 'block')
            self.assertIn('64 KiB', reason)
