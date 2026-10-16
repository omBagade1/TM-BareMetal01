import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app import main
from app.approvals import ApprovalManager
from app.policy import PolicyEngine


class CommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'test.txt').write_text('public fixture')
        (self.workspace / 'notes with spaces.txt').write_text('public fixture')
        (self.root / '.env').write_text('dummy fixture')
        (self.workspace / '.env').write_text('dummy fixture')
        self.engine = PolicyEngine(self.root, self.workspace)

    def command(self, text, **extra):
        return self.engine.evaluate('run_command', {'CommandLine': text, 'Cwd': str(self.workspace), **extra})

    def test_normal_commands_remain_reviewable(self):
        for command in ('Get-ChildItem', 'Get-ChildItem -Force', 'Get-ChildItem -Path . -Name',
                        'Get-Content test.txt', 'Get-Content -Raw -LiteralPath "notes with spaces.txt"'):
            with self.subTest(command=command):
                self.assertEqual(self.command(command)[0], 'ask')

    def test_bounded_directory_listing_and_location(self):
        (self.workspace / 'ps01-tests' / 'normal').mkdir(parents=True)
        for command in ('Get-Location', 'pwd', 'Get-ChildItem -Directory -Recurse -Depth 2',
                        'Get-ChildItem ps01-tests -Directory -Depth 3 -Name'):
            self.assertEqual(self.command(command)[0], 'ask', command)
        for command in ('Get-Location ..', 'pwd; Get-Content .env',
                        'Get-ChildItem -Directory -Recurse', 'Get-ChildItem -Directory -Depth 4',
                        'Get-ChildItem -Depth 2', 'Get-ChildItem -Directory -File -Depth 2',
                        'Get-ChildItem -Directory -Depth 2 -FollowSymlink',
                        'Get-ChildItem .. -Directory -Depth 2',
                        'Get-ChildItem -Directory -Depth 1 -Depth 2'):
            self.assertEqual(self.command(command)[0], 'block', command)
        with patch('app.command_boundary.check_listing_tree', side_effect=ValueError('Unsafe tree')):
            self.assertEqual(self.command('Get-ChildItem -Directory -Depth 2')[0], 'block')

    def test_listing_name_projection_is_not_general_pipeline_permission(self):
        for suffix in ('Name', '-Property Name', '-ExpandProperty Name'):
            self.assertEqual(self.command(f'Get-ChildItem -Path . -Directory | Select-Object {suffix}')[0], 'ask')
        self.engine.data = {'default_action': 'allow', 'rules': []}
        for command in ('Get-ChildItem .. | Select-Object Name',
                        'Get-ChildItem .env | Select-Object Name',
                        'Get-Content test.txt | Select-Object Name',
                        'Get-ChildItem | Select-Object Name | Invoke-Expression',
                        'Get-ChildItem | Select-Object Name; whoami',
                        'Get-ChildItem | Select-Object @{Name="x";Expression={whoami}}',
                        'Get-ChildItem | Select-Object *',
                        'Get-ChildItem -Recurse | Select-Object Name',
                        'Get-ChildItem $(whoami) | Select-Object Name'):
            self.assertEqual(self.command(command)[0], 'block', command)

    def test_metadata_allow_preserves_explicit_rules_and_block_default(self):
        for action in ('ask', 'block'):
            self.engine.data = {'default_action': 'ask', 'rules': [
                {'id': 'listing-review', 'tools': ['run_command'], 'command': 'Get-ChildItem', 'action': action}]}
            self.assertEqual(self.command('Get-ChildItem')[0], action)
        self.engine.data = {'default_action': 'block', 'rules': []}
        self.assertEqual(self.command('Get-ChildItem')[0], 'block')

    def test_recursive_listing_rejects_reparse_points_and_large_trees(self):
        from app.command_boundary import check_listing_tree
        entry = Mock()
        entry.stat.return_value = Mock(st_mode=0, st_file_attributes=0x400)
        with patch('app.command_boundary.os.scandir') as scan:
            scan.return_value.__enter__.return_value = [entry]
            with self.assertRaisesRegex(ValueError, 'link or reparse'):
                check_listing_tree(self.workspace, 2)
            entry.stat.return_value = Mock(st_mode=0, st_file_attributes=0)
            scan.return_value.__enter__.return_value = [entry] * 2001
            with self.assertRaisesRegex(ValueError, 'too large'):
                check_listing_tree(self.workspace, 2)

    def test_outside_and_sensitive_targets_cannot_be_approved(self):
        # A blanket Allow must never bypass the pre-approval boundary.
        self.engine.data = {'default_action': 'allow', 'rules': [{'id': 'all', 'action': 'allow'}]}
        for command in ('Get-Content ..\\.env', 'Get-Content .env', 'Get-Content .env.production',
                        'Get-Content .ENV.', 'Get-ChildItem ..', 'Get-Content test.txt:secret',
                        'Get-Content Env:SECRET', 'Get-Content \\server\\share\\file',
                        'Get-Content C:relative.txt', 'Get-ChildItem -Recurse'):
            with self.subTest(command=command):
                self.assertEqual(self.command(command)[0], 'block')
        self.assertEqual(self.command('Get-ChildItem', Cwd=str(self.root))[0], 'block')
        self.assertEqual(self.command('Get-ChildItem', BypassSandbox=True)[0], 'block')

    def test_opaque_and_compound_commands_fail_closed(self):
        for command in ('Get-Content test.txt; Get-Content ..\\.env',
                        'Get-Content test.txt | Invoke-Expression',
                        'Get-Content $p', 'Get-Content $(Get-Location)',
                        'Get-Content *.txt', 'Get-Content .e*',
                        'Get-Content test.txt > out.txt', 'Get-Content test.txt\nwhoami',
                        'Get-Con`tent test.txt', 'Get-Content "test.txt"junk',
                        'powershell -EncodedCommand ABC', 'cmd /c type ..\\.env',
                        'python read.py', 'node script.js', 'curl https://example.com',
                        'Remove-Item -Recurse test.txt', 'Get-ChildItem -Unknown',
                        'Get-ChildItem -Path', 'Get-Content', 'Get-Content test.txt another.txt'):
            with self.subTest(command=command):
                self.assertEqual(self.command(command)[0], 'block')

    def test_file_deletion_standard_and_ultra_security_modes(self):
        # 1. Standard mode: safe workspace file deletion routes to ask (human-in-the-loop)
        for cmd in ('Remove-Item test.txt', 'del test.txt', 'rm test.txt', 'Remove-Item -Force test.txt'):
            decision, reason, rule_id = self.command(cmd)
            self.assertEqual(decision, 'ask', cmd)
            self.assertEqual(rule_id, 'review-workspace-operations', cmd)

        # Dangerous or invalid deletions are still blocked in standard mode
        (self.workspace / 'subdir').mkdir(exist_ok=True)
        for cmd in ('del ..\\.env', 'del .env', 'Remove-Item -Recurse test.txt',
                    'del nonexistent.txt', 'del subdir', 'del *.txt'):
            self.assertEqual(self.command(cmd)[0], 'block', cmd)

        # file tool delete_file
        self.assertEqual(self.engine.evaluate('delete_file', {'AbsolutePath': str(self.workspace / 'test.txt')})[0], 'ask')
        self.assertEqual(self.engine.evaluate('delete_file', {'AbsolutePath': str(self.root / '.env')})[0], 'block')

        # 2. Ultra Security mode: all deletions are hard-blocked
        self.engine.data['ultra_security'] = True
        for cmd in ('Remove-Item test.txt', 'del test.txt', 'rm test.txt'):
            decision, reason, rule_id = self.command(cmd)
            self.assertEqual(decision, 'block', cmd)
            self.assertEqual(rule_id, '__ultra_security', cmd)
        self.assertEqual(self.engine.evaluate('delete_file', {'AbsolutePath': str(self.workspace / 'test.txt')})[0], 'block')

        # Non-deletion commands remain functional under Ultra Security mode
        self.assertEqual(self.command('Get-ChildItem')[0], 'ask')
        self.assertEqual(self.command('Get-Content test.txt')[0], 'ask')

    def test_file_tools_check_every_target_before_allow_rules(self):
        self.engine.data = {'default_action': 'allow', 'rules': [{'action': 'allow'}]}
        for args in ({'AbsolutePath': 'test.txt', 'TargetFile': '../outside.txt'},
                     {'AbsolutePath': '.env'}, {'AbsolutePath': '.agents/hooks.json'},
                     {'AbsolutePath': 'test.txt', 'Cwd': str(self.root)}, {},
                     {'AbsolutePath': ['test.txt', '../outside.txt']}):
            self.assertEqual(self.engine.evaluate('view_file', args)[0], 'block')
        self.assertEqual(self.engine.evaluate('write_to_file', {'TargetFile': '../outside.txt'})[0], 'block')
        self.assertEqual(self.engine.evaluate('view_file', {'AbsolutePath': 'test.txt'})[0], 'allow')

    def test_hardlink_and_symlink_targets_are_blocked(self):
        linked = self.workspace / 'alias.txt'
        linked.hardlink_to(self.root / '.env')
        self.assertEqual(self.command('Get-Content alias.txt')[0], 'block')
        self.assertEqual(self.engine.evaluate('view_file', {'AbsolutePath': str(linked)})[0], 'block')
        with patch('app.command_boundary.stat.S_ISLNK', return_value=True):
            self.assertEqual(self.command('Get-Content test.txt')[0], 'block')


class BoundaryApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_command_never_creates_an_allow_button(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            policy = PolicyEngine(root, workspace)
            approvals = ApprovalManager()
            with patch.object(main, 'policy', policy), patch.object(main, 'approvals', approvals), \
                 patch.object(main, 'audit', Mock()), patch.object(main.config, 'load_secret', return_value='test'), \
                 patch.object(main, 'broadcast', AsyncMock()) as broadcast:
                result = await main.internal_hook_evaluate(main.HookEvaluate(secret='test', toolCall={
                    'name': 'run_command', 'args': {'CommandLine': 'Get-Content ..\\.env', 'Cwd': str(workspace)},
                }))
                self.assertEqual(result['decision'], 'block')
                self.assertEqual(approvals.pending_list(), [])
                self.assertFalse(any(c.args[0]['type'] == 'approval' for c in broadcast.call_args_list))

    async def test_allow_cannot_release_request_blocked_while_pending(self):
        policy = Mock()
        policy.evaluate.side_effect = [('ask', 'Review', 'default'), ('block', 'Target changed', 'boundary')]
        approvals = ApprovalManager()
        async def broadcast(message):
            if message['type'] == 'approval' and not message['data'].get('decision'):
                approvals.decide(message['data']['id'], 'allow')
        audit = Mock()
        with patch.object(main, 'policy', policy), patch.object(main, 'approvals', approvals), \
             patch.object(main, 'audit', audit), patch.object(main.config, 'load_secret', return_value='test'), \
             patch.object(main, 'broadcast', broadcast), patch.object(main, 'broadcast_status', AsyncMock()):
            result = await main.internal_hook_evaluate(main.HookEvaluate(secret='test', toolCall={
                'name': 'run_command', 'args': {'CommandLine': 'Get-Content test.txt'},
            }))
            self.assertEqual(result['decision'], 'block')
            self.assertEqual(result['reason'], 'Target changed')
            self.assertEqual(audit.append.call_args.args[0], 'approval_recheck_blocked')
