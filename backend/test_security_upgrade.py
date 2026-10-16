"""Unit/integration tests; mocked runner tests do NOT establish OS isolation."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import sqlite3
import hashlib
import subprocess
import sys
import os
from unittest.mock import patch

from app.audit import Audit
from app.approvals import ApprovalManager
from app.policy import PolicyEngine
from app.tool_gateway import ToolGateway, NetworkBroker
from app.ollama_session import OllamaSession
from app import sandbox_worker
from app.windows_sandbox import (IsolationUnavailable, worker_environment, worker_call_directory,
                                 control_directory, workspace_sid_string, WORKER_BOOTSTRAP, worker_diagnostic)


class AuditV2Tests(unittest.TestCase):
    def test_legacy_migration_and_independent_checkpoint(self):
        from app.audit import SCHEMA, GENESIS_HASH
        from verify_audit import verify
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit.db'
            conn = sqlite3.connect(path)
            conn.execute(SCHEMA)
            digest = hashlib.sha256((GENESIS_HASH + '{}').encode()).hexdigest()
            conn.execute('INSERT INTO audit_events VALUES (1,?,?,?,?,?,?)', ('legacy-ts', 'legacy', None, GENESIS_HASH, digest, '{}'))
            conn.commit()
            conn.close()
            audit = Audit(path)
            try:
                self.assertEqual(audit.verify()['legacy_records'], 1)
                self.assertEqual(audit.tail()[0]['ts'], 'legacy-ts')
                audit.append('v2', {'outcome': 'fixture'})
                saved = Path(tmp) / 'independent.json'
                saved.write_text(audit.anchor_path.read_text())
                self.assertTrue(verify(path, saved)['verified'])
                audit.clear()  # privileged full reset rewrites the local anchor
                audit.append('replacement', {})
                self.assertTrue(audit.verify()['verified'])
                self.assertFalse(verify(path, saved)['verified'])
            finally:
                audit._conn.close()

    def test_all_record_fields_and_truncation(self):
        for mutation in ("UPDATE audit_events SET ts='changed' WHERE id=1",
                         "UPDATE audit_events SET event_type='changed' WHERE id=1",
                         "UPDATE audit_events SET decision='allow' WHERE id=1",
                         "UPDATE audit_events SET payload='{}' WHERE id=1",
                         "UPDATE audit_events SET id=9 WHERE id=1",
                         "DELETE FROM audit_events WHERE id=1",
                         "DELETE FROM audit_events WHERE id=2",
                         "DELETE FROM audit_events"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                audit = Audit(Path(tmp) / 'audit.db')
                try:
                    audit.append('one', {'reason': 'fixture'}, 'block')
                    audit.append('two', {})
                    self.assertTrue(audit.verify()['verified'])
                    audit._conn.execute(mutation)
                    audit._conn.commit()
                    self.assertFalse(audit.verify()['verified'])
                    with self.assertRaises(RuntimeError):
                        audit.append('must not extend corrupted log', {})
                finally:
                    audit._conn.close()

    def test_missing_anchor_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit.db'
            audit = Audit(path)
            audit.append('one', {})
            audit._conn.close()
            audit = Audit(path)
            self.assertTrue(audit.verify()['verified'])
            audit.anchor_path.unlink()
            audit._conn.close()
            audit = Audit(path)
            self.assertFalse(audit.verify()['verified'])
            audit._conn.close()

    def test_http_deletion_disabled(self):
        from app.main import audit_clear
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as result:
            asyncio.run(audit_clear())
        self.assertEqual(result.exception.status_code, 403)


class WorkerDirectoryMetadataTests(unittest.TestCase):
    def test_listing_returns_only_bounded_metadata_and_skips_sensitive_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'one.txt').write_text('fixture', encoding='utf-8')
            (root / 'two.txt').write_text('fixture', encoding='utf-8')
            (root / 'subfolder').mkdir()
            (root / '.env').write_text('FAKE_MARKER', encoding='utf-8')
            result = sandbox_worker.run({'tool': 'list_directory', 'args': {'path': tmp}})
        self.assertEqual(result['file_count'], 2)
        self.assertTrue(result['count_is_exact'])
        self.assertEqual([item['name'] for item in result['files']], ['one.txt', 'two.txt'])
        self.assertEqual(result['directories'], ['subfolder'])
        self.assertEqual(result['skipped'], 1)

class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'note.txt').write_text('fake fixture')
        self.audit = Audit(self.root / 'audit.db')
        self.policy = PolicyEngine(self.root, self.workspace)
        self.events = []
        self.executed = []
        async def broadcast(event):
            self.events.append(event)
        owner = self
        class Runner:
            def execute(self, tool, args):
                owner.executed.append((tool, args))
                return {'ok': True}
        self.approvals = ApprovalManager()
        self.gateway = ToolGateway(self.policy, self.approvals, self.audit, Runner(), broadcast)

    async def asyncTearDown(self):
        self.audit._conn.close()
        self.temp.cleanup()

    async def test_unknown_arguments_and_escape_never_reach_runner(self):
        for tool, args in [('eval', {}), ('read_file', {'path': '../fake.txt'}),
                           ('read_file', {'path': 'note.txt', 'bypass': True}),
                           ('shell', {'command': 'Get-Location; whoami'}),
                           ('http_request', {'url': 'http://127.0.0.1:19888/', 'method': 'POST'})]:
            result = await self.gateway.call(tool, args)
            self.assertEqual(result['attribution'], 'AGENTGUARD_POLICY_BLOCK')
            self.assertTrue(result['audit_ids'])
        self.assertEqual(self.executed, [])
        notices = [e['data'] for e in self.events if e['type'] == 'action_issue']
        self.assertEqual(len(notices), 5)
        for notice in notices:
            self.assertEqual(notice['decision'], 'block')
            self.assertTrue(notice['payload']['reason'])
            self.assertTrue(any(row['id'] == notice['id'] for row in self.audit.tail()))

    async def test_unmatched_action_blocks_with_chat_notice_and_reason(self):
        self.policy.set_policy({'default_action': 'block', 'rules': []})
        result = await self.gateway.call('read_file', {'path': 'note.txt'})
        self.assertFalse(result['ok'])
        self.assertIn('No matching policy rule', result['reason'])
        notices = [e['data'] for e in self.events if e['type'] == 'action_issue']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['payload']['reason'], result['reason'])
        self.assertFalse(self.executed)
        self.assertFalse(self.approvals.pending_list())

    async def test_real_approval_wait_and_recheck(self):
        task = asyncio.create_task(self.gateway.call('read_file', {'path': 'note.txt'}))
        for _ in range(20):
            if self.approvals.pending_list():
                break
            await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertFalse(self.executed)
        self.policy.set_policy({'default_action': 'block', 'rules': []})
        self.approvals.decide(self.approvals.pending_list()[0]['id'], 'allow')
        self.assertFalse((await task)['ok'])
        self.assertFalse(self.executed)

    async def test_timeout_and_setup_failure_attribution(self):
        with patch('app.config.APPROVAL_TIMEOUT', .01):
            self.assertFalse((await self.gateway.call('read_file', {'path': 'note.txt'}))['ok'])
        self.policy.set_policy({'default_action': 'allow', 'rules': []})
        with patch.object(self.gateway.runner, 'execute', side_effect=IsolationUnavailable('setup missing')):
            result = await self.gateway.call('read_file', {'path': 'note.txt'})
        self.assertEqual(result['attribution'], 'NOT_TESTED')

    async def test_write_content_redacted_from_audit(self):
        self.policy.set_policy({'default_action': 'allow', 'rules': []})
        result = await self.gateway.call('write_file', {'path': 'new.txt', 'content': 'FAKE_SECRET_MARKER'})
        self.assertTrue(result['ok'])
        self.assertNotIn('FAKE_SECRET_MARKER', json.dumps(self.audit.tail()))

    async def test_directory_listing_is_bounded_read_only_metadata(self):
        task = asyncio.create_task(self.gateway.call('list_directory', {}))
        for _ in range(100):
            if self.approvals.pending_list():
                break
            await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertFalse(self.executed)
        self.approvals.decide(self.approvals.pending_list()[0]['id'], 'allow')
        result = await task
        self.assertEqual(result['attribution'], 'EXECUTED')
        self.assertEqual(self.executed[0][0], 'list_directory')
        self.assertEqual(self.executed[0][1]['path'], str(self.workspace))
        self.assertTrue(any(row['event_type'] == 'policy_eval' and row['decision'] == 'ask'
                            for row in self.audit.tail()))
        self.assertEqual((await self.gateway.call('list_directory', {'path': '../'}))['attribution'],
                         'AGENTGUARD_POLICY_BLOCK')
        self.assertEqual((await self.gateway.call('list_directory', {'path': 'note.txt'}))['attribution'],
                         'AGENTGUARD_POLICY_BLOCK')
        self.assertEqual(len(self.executed), 1)

    async def test_model_tool_calls_use_gateway(self):
        events = []
        async def emit(evt):
            events.append(evt)
        session = OllamaSession(emit, self.gateway)
        await session.start(str(self.workspace))
        response = {'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'read_file', 'arguments': {'path': '../fake.txt'}}}]}
        with patch('app.ollama_session.chat', side_effect=[response, {'role': 'assistant', 'content': 'blocked'}]):
            await session.send('read')
            await session.task
        self.assertFalse(self.executed)
        self.assertTrue(any(e['event'] == 'result' for e in events))
        self.assertTrue(any(e['event_type'] == 'policy_eval' for e in self.audit.tail()))

    async def test_setup_failure_does_not_return_to_model_for_explanation(self):
        self.policy.set_policy({'default_action': 'allow', 'rules': []})
        events = []
        async def emit(evt):
            events.append(evt)
        session = OllamaSession(emit, self.gateway)
        await session.start(str(self.workspace))
        response = {'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'read_file', 'arguments': {'path': 'note.txt'}}}]}
        with patch('app.ollama_session.chat', return_value=response) as model, \
                patch.object(self.gateway.runner, 'execute', side_effect=IsolationUnavailable('control directory is absent')):
            await session.send('read note.txt')
            await session.task
        self.assertEqual(model.call_count, 1)
        final = events[-1]['payload']
        self.assertEqual(final['status'], 'error')
        self.assertEqual(final['attribution'], 'NOT_TESTED')
        self.assertIn('does not establish whether', final['response'])
        self.assertTrue(final['audit_ids'])


class NetworkValidationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows temporary-directory ACL regression')
    def test_call_directory_grants_package_and_captures_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'workspace'
            workspace.mkdir()
            control_directory(workspace).mkdir()
            sid = workspace_sid_string(workspace)
            with worker_call_directory(workspace) as call:
                request = call / 'request.json'
                request.write_text('{}')
                for path in (call, request):
                    permissions = subprocess.run(['icacls.exe', str(path)], capture_output=True, text=True, check=True)
                    self.assertIn(sid, permissions.stdout)
                diagnostic = call / 'startup-error.txt'
                response = call / 'response.json'
                worker = Path(__file__).parent / 'app/sandbox_worker.py'
                process = subprocess.run([sys.executable, '-I', '-B', '-c', WORKER_BOOTSTRAP,
                                          str(worker), str(request), str(response), str(diagnostic)],
                                         capture_output=True, text=True, timeout=10)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('Worker requires AppContainer', worker_diagnostic(diagnostic))
                self.assertFalse(response.exists())
            self.assertFalse(call.exists())

    def test_worker_environment_contains_profile_bootstrap_without_host_secrets(self):
        with patch.dict(os.environ, {'AGENTGUARD_SECRET': 'FAKE_HOOK_SECRET',
                                     'HTTP_PROXY': 'http://fake-proxy.invalid',
                                     'USERPROFILE': 'HOST_PROFILE', 'LOCALAPPDATA': 'HOST_APPDATA',
                                     'PYTHONPATH': 'HOST_IMPORTS', 'CLOUD_TOKEN': 'FAKE_TOKEN'}):
            env = worker_environment('CALL_TEMP', 'CONTAINER_PROFILE')
        self.assertEqual(env['LOCALAPPDATA'], 'CONTAINER_PROFILE')
        self.assertEqual(env['APPDATA'], 'CONTAINER_PROFILE')
        self.assertEqual(env['USERPROFILE'], 'CONTAINER_PROFILE')
        self.assertEqual(env['TEMP'], 'CALL_TEMP')
        self.assertEqual(env['TMP'], 'CALL_TEMP')
        self.assertEqual(set(env), {'SystemRoot', 'WINDIR', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP'})
        self.assertNotIn('FAKE', json.dumps(env))
        self.assertNotIn('HOST_', json.dumps(env))

    def test_real_local_broker_delivery_without_dns(self):
        from security_harness import Receivers
        with Receivers() as receiver:
            broker = NetworkBroker({receiver.url.rstrip('/'): '127.0.0.1'})
            args = broker.validate({'url': receiver.url, 'method': 'POST', 'body': 'FAKE_ONLY'})
            result = broker.execute(args)
            self.assertTrue(result['ok'])
            self.assertEqual(receiver.http_deliveries[0]['body'], 'FAKE_ONLY')

    def test_exact_origins_no_credentials_or_alt_ports(self):
        broker = NetworkBroker({'http://fixture.test:19888': '127.0.0.1'})
        self.assertEqual(broker.validate({'url': 'http://fixture.test:19888/x'})['ip'], '127.0.0.1')
        for url in ('http://fixture.test:19889/', 'http://fixture.test.evil:19888/',
                    'http://user@fixture.test:19888/', 'http://127.0.0.1:19888/',
                    'file:///fake', 'http://fixture.test:19888/#fragment',
                    'http://[::1]:19888/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                broker.validate({'url': url})

    @unittest.skipUnless(os.name == 'nt', 'Windows worker self-check')
    def test_worker_refuses_ambient_token_before_touching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.json'
            worker = Path(__file__).parent / 'app/sandbox_worker.py'
            result = subprocess.run([sys.executable, '-I', '-B', str(worker), str(Path(tmp) / 'missing.json'), str(output)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Worker requires AppContainer', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
