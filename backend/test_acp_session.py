import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app import main
from app.acp_session import GeminiAcpSession, startup_error_message
from app.approvals import ApprovalManager
from app.policy import PolicyEngine


class AcpTests(unittest.IsolatedAsyncioTestCase):
    def test_unsupported_login_has_actionable_error(self):
        message = startup_error_message('This client is no longer supported for Gemini Code Assist for individuals.')
        self.assertIn('provider access restriction', message)
        self.assertIn('Gemini API key or Vertex AI', message)
        self.assertIn('Antigravity CLI', message)
        self.assertEqual(startup_error_message('Connection failed'), 'Connection failed')

    def test_legacy_sandbox_setting_does_not_enable_acp_sandbox(self):
        request = main.SessionStart(provider='gemini-acp', sandbox=True)
        self.assertFalse(request.acp_sandbox)
        self.assertTrue(main.SessionStart(provider='gemini-acp', acp_sandbox=True).acp_sandbox)

    async def test_launch_honors_explicit_sandbox_selection(self):
        for enabled in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                session = GeminiAcpSession(AsyncMock(), AsyncMock())
                session._entrypoint = Path(tmp) / 'gemini.js'
                session._read_stdout = AsyncMock()
                session._read_stderr = AsyncMock()
                session._request = AsyncMock(side_effect=[{}, {'sessionId': 'test'}])
                session._write = AsyncMock()
                proc = Mock(returncode=None)
                with patch('app.acp_session.shutil.which', return_value='node'), \
                     patch('app.acp_session.os.environ', {'GEMINI_SANDBOX': 'true'}), \
                     patch('app.acp_session.config.DATA_DIR', Path(tmp)), \
                     patch('app.acp_session.config.load_secret', return_value='test'), \
                     patch('app.acp_session.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)) as spawn:
                    await session.start(tmp, sandbox=enabled)
                    self.assertIn('--sandbox' if enabled else '--sandbox=false', spawn.call_args.args)
                    self.assertEqual(spawn.call_args.kwargs['env']['GEMINI_SANDBOX'], 'true' if enabled else 'false')
                    await session._reader
                    await session._stderr_reader
                    session._stderr_log.close()

    async def test_permission_waits_for_user_and_rechecks_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = PolicyEngine(root, root)
            approvals = ApprovalManager()
            with patch.object(main, 'policy', policy), patch.object(main, 'approvals', approvals), \
                 patch.object(main, 'audit', Mock()), patch.object(main, 'broadcast', AsyncMock()), \
                 patch.object(main, 'broadcast_status', AsyncMock()):
                for decision, change_policy in [('allow', False), ('block', False), ('allow', True)]:
                    policy.data = {'default_action': 'ask', 'rules': []}
                    task = asyncio.create_task(main.handle_acp_permission({
                        'toolCall': {'kind': 'execute', 'title': 'command',
                                     'rawInput': {'command': 'Get-Location'}}}))
                    for _ in range(100):
                        if approvals.pending_list():
                            break
                        await asyncio.sleep(.01)
                    self.assertFalse(task.done())
                    if change_policy:
                        policy.data['default_action'] = 'block'
                    approvals.decide(approvals.pending_list()[0]['id'], decision)
                    self.assertEqual(await asyncio.wait_for(task, 1), 'block' if change_policy else decision)

    async def test_sandbox_error_survives_process_exit(self):
        session = GeminiAcpSession(AsyncMock(), AsyncMock())
        stderr = asyncio.StreamReader()
        stderr.feed_data(b'GEMINI_SANDBOX is true but failed to determine command for sandbox\n')
        stderr.feed_eof()
        stdout = asyncio.StreamReader()
        stdout.feed_eof()
        session.proc = Mock(stderr=stderr, stdout=stdout, returncode=1, wait=AsyncMock())
        session._stderr_reader = asyncio.create_task(session._read_stderr())
        future = asyncio.get_running_loop().create_future()
        session._responses[1] = future
        await session._read_stdout()
        with self.assertRaisesRegex(RuntimeError, 'Install Docker or Podman'):
            await future

    async def test_permission_response_uses_allow_once_only(self):
        session = GeminiAcpSession(AsyncMock(), AsyncMock(return_value='allow'))
        session._write = AsyncMock()
        await session._handle_permission({'id': 7, 'params': {'options': [
            {'kind': 'allow_always', 'optionId': 'always'},
            {'kind': 'allow_once', 'optionId': 'once'}]}})
        self.assertEqual(session._write.call_args.args[0]['result']['outcome']['optionId'], 'once')
