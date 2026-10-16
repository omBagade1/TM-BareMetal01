import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from app import main
from app.workspace_files import checked_directory, list_workspace_files


class WorkspaceFileTests(unittest.TestCase):
    def test_listing_and_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace'
            root.mkdir()
            (root / 'test.txt').write_bytes(b'hello')
            (root / 'nested').mkdir()
            (root / 'nested' / 'hidden.txt').write_bytes(b'not listed')
            result = list_workspace_files(root, str(root))
            self.assertEqual(result['files'], [{'name':'test.txt', 'size_bytes':5}])
            for outside in (str(root.parent), '..'):
                with self.assertRaises(ValueError):
                    checked_directory(root, outside)
            self.assertTrue(list_workspace_files(root, str(root), limit=1)['truncated'])

    def test_link_resolution_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace'
            root.mkdir()
            with patch.object(Path, 'resolve', side_effect=[root, root.parent]):
                with self.assertRaises(ValueError):
                    checked_directory(root, 'linked-directory')


class WorkspaceEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_block_prevents_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(main.config, 'WORKSPACE_DIR', Path(tmp)), \
                 patch.object(main.config, 'load_secret', return_value='test'), \
                 patch.object(main, 'audit', Mock()), \
                 patch.object(main, 'internal_hook_evaluate', AsyncMock(return_value={'decision':'block'})), \
                 patch.object(main, 'list_workspace_files') as listing:
                with self.assertRaises(HTTPException) as caught:
                    await main.workspace_files(main.FileListingRequest())
                self.assertEqual(caught.exception.status_code, 403)
                listing.assert_not_called()

    async def test_allowed_listing_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'test.txt').write_bytes(b'hello')
            audit = Mock()
            audit.append.return_value = {'id':123}
            with patch.object(main.config, 'WORKSPACE_DIR', Path(tmp)), \
                 patch.object(main.config, 'load_secret', return_value='test'), \
                 patch.object(main, 'audit', audit), \
                 patch.object(main, 'internal_hook_evaluate', AsyncMock(return_value={'decision':'allow'})) as gate:
                result = await main.workspace_files(main.FileListingRequest())
                self.assertEqual(result['files'], [{'name':'test.txt','size_bytes':5}])
                self.assertEqual(result['audit_id'], 123)
                self.assertEqual(gate.call_args.args[0].toolCall['name'], 'list_dir')
                self.assertEqual(audit.append.call_args.args[0], 'tool_result')
