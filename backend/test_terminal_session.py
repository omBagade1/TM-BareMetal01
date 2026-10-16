import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from app import main
from app.approvals import ApprovalManager
from app.terminal_session import AgyTerminalSession


class TerminalSessionTests(unittest.IsolatedAsyncioTestCase):
    def session(self):
        session = AgyTerminalSession(AsyncMock())
        session.proc = Mock()
        return session

    async def test_only_controller_can_answer_and_input_is_exact(self):
        session = self.session()
        owner, observer = object(), object()
        queue, first = session.attach(owner)
        _, second = session.attach(observer)
        self.assertTrue(first['writable'])
        self.assertFalse(second['writable'])
        with self.assertRaises(RuntimeError):
            await session.input(observer, '\r')
        for value in ('\x1b[B', '\r', 'λ'):
            await session.input(owner, value)
            session.proc.write.assert_called_with(value)
        session.detach(owner, queue)
        with self.assertRaises(RuntimeError):
            await session.input(owner, '\r')

    async def test_end_and_invalid_messages_cannot_write(self):
        session = self.session()
        owner = object()
        session.attach(owner)
        for value in (None, '', 'x' * 8193):
            with self.assertRaises(ValueError):
                await session.input(owner, value)
        for cols, rows in ((True, 30), (0, 30), (80, 999), ('80', 30)):
            with self.assertRaises(ValueError):
                await session.resize(owner, cols, rows)
        session._ended = True
        with self.assertRaises(RuntimeError):
            await session.input(owner, '\r')
        session.proc.write.assert_not_called()

    async def test_overlapping_reconnect_promotes_remaining_browser(self):
        session = self.session()
        first, second = object(), object()
        old_queue, _ = session.attach(first)
        new_queue, snapshot = session.attach(second)
        self.assertFalse(snapshot['writable'])
        session.detach(first, old_queue)
        self.assertEqual(await new_queue.get(), {'type': 'control', 'writable': True})
        await session.input(second, 'hello')
        session.proc.write.assert_called_once_with('hello')

    async def test_explicit_takeover_revokes_previous_controller(self):
        session = self.session()
        first, second = object(), object()
        first_queue, _ = session.attach(first)
        second_queue, _ = session.attach(second)
        session.claim(second)
        self.assertEqual(await first_queue.get(), {'type': 'control', 'writable': False})
        self.assertEqual(await second_queue.get(), {'type': 'control', 'writable': True})
        with self.assertRaises(RuntimeError):
            await session.input(first, '\r')
        await session.input(second, 'x')
        session.proc.write.assert_called_once_with('x')
        with self.assertRaises(RuntimeError):
            session.claim(object())

    async def test_takeover_rejects_old_input_waiting_for_io_lock(self):
        session = self.session()
        first, second = object(), object()
        session.attach(first)
        session.attach(second)
        await session._io_lock.acquire()
        task = asyncio.create_task(session.input(first, '\r'))
        await asyncio.sleep(0)
        session.claim(second)
        session._io_lock.release()
        with self.assertRaises(RuntimeError):
            await task
        session.proc.write.assert_not_called()

    async def test_resize_and_overflow(self):
        session = self.session()
        owner = object()
        queue, _ = session.attach(owner)
        await session.resize(owner, 90, 25)
        session.proc.setwinsize.assert_called_once_with(25, 90)
        for _ in range(300):
            session._publish({'type': 'output', 'data': 'x'})
        self.assertEqual(await queue.get(), {'type': 'overflow'})
        self.assertNotIn(queue, session._subscribers)

    async def test_reader_replay_is_bounded_and_never_sends_input(self):
        session = self.session()
        session.proc.read.side_effect = ['x' * 1_100_000, 'y' * 1_100_000, EOFError()]
        session._close_process = AsyncMock()
        await session._read()
        _, snapshot = session.attach(object())
        self.assertTrue(snapshot['truncated'])
        self.assertTrue(snapshot['ended'])
        self.assertEqual(snapshot['data'], 'y' * 1_100_000)
        session.proc.write.assert_not_called()

    async def test_duplicate_start_preserves_running_process(self):
        existing = self.session()
        with patch.object(main, 'session', existing):
            with self.assertRaises(main.HTTPException) as result:
                await main.session_start(main.SessionStart(interactive=True))
            self.assertEqual(result.exception.status_code, 409)
            self.assertIs(main.session, existing)

    async def test_interactive_asks_always_require_dashboard_review(self):
        session = self.session()
        review = {'id': 'review', 'ts': 'now', 'tool': 'run_command', 'args': {},
                  'reason': 'Review', 'decision': 'allow', 'decided_by': 'human'}
        for action, tool, terminal_id, ended, expected, queued in (
            ('ask', 'run_command', session.terminal_id, False, 'allow', True),
            ('block', 'run_command', session.terminal_id, False, 'block', False),
            ('allow', 'run_command', session.terminal_id, False, 'allow', False),
            ('ask', 'view_file', session.terminal_id, False, 'allow', True),
            ('ask', 'run_command', 'stale-session', False, 'allow', True),
            ('ask', 'run_command', None, False, 'allow', True),
            ('ask', 'run_command', session.terminal_id, True, 'allow', True),
        ):
            with self.subTest(action=action, tool=tool, terminal_id=terminal_id, ended=ended):
                session._ended = ended
                policy = Mock()
                policy.evaluate.return_value = (action, 'Review', 'test-rule')
                approvals = Mock(request=AsyncMock(return_value=review))
                audit = Mock()
                with patch.object(main, 'session', session), patch.object(main, 'policy', policy), \
                     patch.object(main, 'approvals', approvals), patch.object(main, 'audit', audit), \
                     patch.object(main.config, 'load_secret', return_value='secret'), \
                     patch.object(main, 'broadcast', AsyncMock()), patch.object(main, 'broadcast_status', AsyncMock()):
                    result = await main.internal_hook_evaluate(main.HookEvaluate(
                        secret='secret', terminal_id=terminal_id,
                        toolCall={'name': tool, 'args': {'CommandLine': 'Get-ChildItem'}},
                    ))
                    self.assertEqual(result['decision'], expected)
                    self.assertEqual(approvals.request.await_count, int(queued))
                    self.assertFalse(any(call.args[0] == 'approval_delegated'
                                         for call in audit.append.call_args_list))

    async def test_interactive_hook_waits_for_real_queue_decision(self):
        session = self.session()
        for decision in ('allow', 'block', 'timeout'):
            with self.subTest(decision=decision):
                approvals = ApprovalManager()
                requested = asyncio.Event()
                async def broadcast(message):
                    if message.get('type') == 'approval' and not message['data'].get('decision'):
                        requested.set()
                policy = Mock()
                policy.evaluate.return_value = ('ask', 'Review', 'test-rule')
                with patch.object(main, 'session', session), patch.object(main, 'policy', policy), \
                     patch.object(main, 'approvals', approvals), patch.object(main, 'audit', Mock()), \
                     patch.object(main.config, 'load_secret', return_value='secret'), \
                     patch.object(main.config, 'APPROVAL_TIMEOUT', 0.05 if decision == 'timeout' else 10), \
                     patch.object(main, 'broadcast', broadcast), patch.object(main, 'broadcast_status', AsyncMock()):
                    task = asyncio.create_task(main.internal_hook_evaluate(main.HookEvaluate(
                        secret='secret', terminal_id=session.terminal_id,
                        toolCall={'name': 'run_command', 'args': {'CommandLine': 'Get-ChildItem'}},
                    )))
                    await asyncio.wait_for(requested.wait(), 2)
                    self.assertFalse(task.done(), 'No CLI hook answer before human review')
                    pending = approvals.pending_list()
                    self.assertEqual(len(pending), 1)
                    if decision != 'timeout':
                        approvals.decide(pending[0]['id'], decision)
                    result = await asyncio.wait_for(task, 2)
                    self.assertEqual(result['decision'], 'block' if decision == 'timeout' else decision)
                    self.assertEqual(approvals.pending_list(), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows ConPTY integration')
    async def test_real_conpty_menu_selection(self):
        # Real ConPTY + a deterministic local menu; no provider or credentials.
        from winpty import PtyProcess
        spawn = PtyProcess.spawn
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'menu.py'
            fixture.write_text(
                "import msvcrt\n"
                "print('Choose: Allow once / Block', flush=True)\n"
                "key = msvcrt.getwch()\n"
                "print('SELECTED:' + ('Block' if key == '2' else 'Allow once'), flush=True)\n",
                encoding='utf-8',
            )
            session = AgyTerminalSession(AsyncMock())
            owner = object()
            with patch('winpty.PtyProcess.spawn', side_effect=lambda *a, **kw: spawn([sys.executable, '-u', str(fixture)], **kw)), \
                 patch.object(main.config, 'load_secret', return_value='test-secret'):
                await session.start(directory, sandbox=False)
            queue, snapshot = session.attach(owner)
            output = snapshot['data']
            try:
                async with asyncio.timeout(15):
                    while 'Choose:' not in output:
                        output += (await queue.get()).get('data', '')
                    await session.input(owner, '2')
                    while 'SELECTED:Block' not in output:
                        output += (await queue.get()).get('data', '')
                self.assertIn('Allow once / Block', output)
            finally:
                await session.stop()


class TerminalWebSocketTests(unittest.TestCase):
    def test_origin_session_and_explicit_input(self):
        session = AgyTerminalSession(AsyncMock())
        session.proc = Mock()
        session.input = AsyncMock()
        client = TestClient(main.app)
        endpoint = '/ws/terminal/' + session.terminal_id
        with patch.object(main, 'session', session):
            for origin in (None, 'https://untrusted.example'):
                headers = {'origin': origin} if origin else {}
                with self.assertRaises(Exception) as caught:
                    with client.websocket_connect(endpoint, headers=headers):
                        pass
                self.assertEqual(caught.exception.code, 1008)
            headers = {'origin': main.config.BACKEND_URL}
            with self.assertRaises(Exception) as caught:
                with client.websocket_connect('/ws/terminal/stale-id', headers=headers):
                    pass
            self.assertEqual(caught.exception.code, 1008)
            with client.websocket_connect(endpoint, headers=headers) as ws:
                self.assertEqual(ws.receive_json()['type'], 'snapshot')
                ws.send_json({'type': 'input', 'data': '\x1b[B'})
                ws.send_json({'type': 'invalid'})
                self.assertEqual(ws.receive_json()['type'], 'error')
                session.input.assert_awaited_once()
                self.assertEqual(session.input.call_args.args[1], '\x1b[B')
        self.assertIsNone(session._controller)


if __name__ == '__main__':
    unittest.main()
