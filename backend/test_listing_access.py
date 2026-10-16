import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.policy import PolicyEngine
from configure_cli_listing import merged_settings
import list_workspace


class ListingAccessTests(unittest.TestCase):
    def test_settings_merge_is_narrow_and_idempotent(self):
        original = {'theme':'dark','permissions':{'allow':['command(git status)'], 'deny':['command(rm)']}}
        grant = 'command(C:/app/list-workspace.cmd)'
        result = merged_settings(original, grant)
        self.assertEqual(result['permissions']['allow'], ['command(git status)', grant])
        self.assertEqual(result['permissions']['deny'], ['command(rm)'])
        self.assertEqual(result['theme'], 'dark')
        self.assertEqual(len(original['permissions']['allow']), 1)
        self.assertEqual(merged_settings(result, grant), result)

    def test_guard_rejects_outside_paths_extra_commands_and_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / 'workspace'
            workspace.mkdir()
            engine = PolicyEngine(root, workspace)
            access = {'command': 'C:/app/list-workspace.cmd'}
            args = {'CommandLine':access['command'], 'Cwd':str(workspace)}
            with patch('app.policy.load_listing_access', return_value=access):
                self.assertEqual(engine.evaluate('run_command', args)[0], 'ask')
                for change in ({'Cwd':str(root)}, {'Cwd':'..'}, {'Cwd':None},
                               {'CommandLine':access['command']+' extra'},
                               {'CommandLine':access['command']+'; Get-Content private.txt'},
                               {'IsDaemon':True}, {'BypassSandbox':True}):
                    self.assertEqual(engine.evaluate('run_command', {**args, **change})[0], 'block')
                engine.data['rules'].insert(0, {'id':'user-block','action':'block','tools':['run_command']})
                self.assertEqual(engine.evaluate('run_command', args)[2], 'user-block')

    def test_helper_reads_fixed_target_and_rejects_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'test.txt').write_bytes(b'12345')
            (root / 'data' / 'listing-access.json').write_text(json.dumps({'workspace':str(workspace.resolve())}))
            with patch.object(list_workspace, '__file__', str(root / 'backend' / 'list_workspace.py')), \
                 patch('sys.argv', ['list_workspace.py']):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    list_workspace.main()
                self.assertEqual(json.loads(out.getvalue())['files'], [{'name':'test.txt','size_bytes':5}])
                with patch('sys.argv', ['list_workspace.py', str(root)]):
                    with self.assertRaises(ValueError):
                        list_workspace.main()
