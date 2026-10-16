"""Focused regression checks. Run: python -m unittest discover -s backend -p 'test_*.py'."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.approvals import ApprovalManager
from app.audit import Audit
from app.policy import PolicyEngine


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_notification_and_serializable_history(self):
        manager = ApprovalManager()
        async def notify(rec):
            self.assertEqual(manager.pending_list()[0]["id"], rec["id"])
            manager.decide(rec["id"], "allow")
        result = await manager.request("view_file", {}, "Review", on_pending=notify)
        self.assertEqual(result["decision"], "allow")
        self.assertFalse(manager.pending_list())
        json.dumps(manager.history())

    async def test_timeout_blocks(self):
        with patch("app.config.APPROVAL_TIMEOUT", .01):
            result = await ApprovalManager().request("view_file", {}, "Review")
        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["decided_by"], "timeout")


class PolicyTests(unittest.TestCase):
    def test_default_deny_and_unknown_tools_cannot_be_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PolicyEngine(Path(tmp), Path(tmp))
            self.assertEqual(engine.get_policy()['default_action'], 'block')
            self.assertEqual(engine.evaluate('view_file', {'path': 'note.txt'})[0], 'ask')
            engine.set_policy({'default_action': 'block', 'rules': []})
            decision, reason, _ = engine.evaluate('view_file', {'path': 'note.txt'})
            self.assertEqual(decision, 'block')
            self.assertIn('No matching policy rule', reason)
            engine.set_policy({'default_action': 'allow', 'rules': [{'action': 'allow'}]})
            for tool in ('unknown_tool', 'http_request', 'web_fetch', 'execute_browser_javascript'):
                self.assertEqual(engine.evaluate(tool, {'path': 'note.txt', 'url': 'https://collector.ps01.test'})[0], 'block')
            self.assertEqual(engine.evaluate('http_request', {'url': 'https://approved.test'}, broker_validated=True)[0], 'allow')

    def test_containment_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = PolicyEngine(root, root / "workspace")
            self.assertEqual(engine.evaluate("view_file", {"AbsolutePath": "test.txt"})[0], "ask")
            self.assertEqual(engine.evaluate("view_file", {"AbsolutePath": "../outside.txt"})[0], "block")
            before = engine.get_policy()
            with self.assertRaises(ValueError):
                engine.set_policy({"default_action": "invalid", "rules": []})
            with self.assertRaises(ValueError):
                engine.set_policy({"default_action": "ask", "ultra_security": "not_bool", "rules": []})
            self.assertEqual(engine.get_policy(), before)
            with self.assertRaises(ValueError):
                engine.set_policy({"default_action": "ask", "rules": [{"action": "allow", "command_re": "["}]})

    def test_ultra_security_api_toggle(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            resp = client.post('/api/policy/ultra-security', json={'enabled': True})
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json().get('ultra_security'))
            status = client.get('/api/status').json()
            self.assertTrue(status.get('ultra_security'))
            resp2 = client.post('/api/policy/ultra-security', json={'enabled': False})
            self.assertEqual(resp2.status_code, 200)
            self.assertFalse(resp2.json().get('ultra_security'))
            status2 = client.get('/api/status').json()
            self.assertFalse(status2.get('ultra_security'))

    def test_cli_builtin_skills_and_credentials_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = PolicyEngine(root, root / "workspace")
            skills = root / ".gemini" / "antigravity-cli" / "builtin" / "skills"
            skills.mkdir(parents=True)
            engine.builtin_skills = skills
            skill = skills / "guide" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("Skill instructions")
            secret = root / ".gemini" / "oauth_creds.json"
            secret.write_text("test fixture only")
            for tool in ("view_file", "read_file"):
                self.assertEqual(engine.evaluate(tool, {"AbsolutePath": str(skill)})[0], "allow")
                for path in (secret, skills / ".." / ".." / ".." / "oauth_creds.json",
                             root / "other" / ".gemini" / "antigravity-cli" / "builtin" / "skills" / "SKILL.md",
                             skills / "missing.md"):
                    self.assertEqual(engine.evaluate(tool, {"AbsolutePath": str(path)})[0], "block")
                self.assertEqual(engine.evaluate(tool, {"AbsolutePath": str(skill), "Path": str(secret)})[0], "block")
            for tool in ("write_to_file", "replace_file_content", "list_dir", "grep_search"):
                self.assertEqual(engine.evaluate(tool, {"TargetFile": str(skill)})[0], "block")
            # A user block before the exception continues to take precedence.
            engine.data['rules'].insert(0, {'id':'custom', 'action':'block', 'tools':['view_file']})
            self.assertEqual(engine.evaluate('view_file', {'AbsolutePath':str(skill)})[2], 'custom')

    def test_builtin_skill_link_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = PolicyEngine(root, root / 'workspace')
            skills = root / 'skills'
            skills.mkdir()
            engine.builtin_skills = skills
            link = skills / 'SKILL.md'
            link.write_text('fixture')
            outside = root / 'private.txt'
            outside.write_text('fixture')
            # Windows does not always permit creating symlinks; model the OS
            # resolution result to exercise the same containment decision.
            with patch.object(Path, 'resolve', return_value=outside):
                self.assertFalse(engine._is_builtin_skill_read('view_file', {'AbsolutePath':str(link)}))

    def test_clear_audit_restarts_chain_without_reusing_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp) / 'audit.db')
            try:
                old = audit.append('test', {'action': 'read'})
                self.assertEqual(audit.clear(), {'cleared': 1, 'through_id': old['id']})
                self.assertEqual(audit.tail(), [])
                self.assertTrue(audit.verify()['verified'])
                new = audit.append('test', {'action': 'write'})
                self.assertGreater(new['id'], old['id'])
                self.assertTrue(audit.verify()['verified'])
                audit.clear()
                self.assertEqual(audit.clear()['cleared'], 0)
            finally:
                audit._conn.close()

    def test_audit_detects_payload_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Audit(Path(tmp) / "audit.db")
            audit.append("test", {"action": "read"})
            self.assertTrue(audit.verify()["verified"])
            audit._conn.execute("UPDATE audit_events SET payload = '{}' WHERE id = 1")
            audit._conn.commit()
            self.assertFalse(audit.verify()["verified"])
            audit._conn.close()


if __name__ == "__main__":
    unittest.main()
