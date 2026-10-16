"""Run under the user's normal account to install a single CLI helper grant."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def merged_settings(data: dict, grant: str) -> dict:
    # Validate before touching the original file; preserve unrelated settings.
    result = json.loads(json.dumps(data))
    permissions = result.setdefault('permissions', {})
    if not isinstance(permissions, dict):
        raise ValueError('Existing permissions must be an object')
    allowed = permissions.setdefault('allow', [])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise ValueError('Existing permissions.allow must be an array of strings')
    if grant not in allowed:
        allowed.append(grant)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and update CLI settings')
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    workspace = Path(os.environ.get('AGENTGUARD_WORKSPACE', root / 'workspace')).resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError('Workspace must be a directory')
    if root.is_relative_to(workspace):
        raise ValueError('The agent workspace must not include the application/helper installation')
    wrapper = root / 'list-workspace.cmd'
    command = wrapper.as_posix()
    # Keep the CLI resource target a single unambiguous token.
    if any(c.isspace() or c in '()&|<>^%!' for c in command):
        raise ValueError('The application path must not contain spaces or shell metacharacters for this helper')
    settings = Path.home() / '.gemini' / 'antigravity-cli' / 'settings.json'
    original = settings.read_bytes() if settings.exists() else None
    data = json.loads(original.decode('utf-8-sig')) if original is not None else {}
    if not isinstance(data, dict):
        raise ValueError('CLI settings must be an object')
    grant = f'command({command})'
    updated = merged_settings(data, grant)
    print(f'Workspace: {workspace}\nCLI permission to add: {grant}\nSettings: {settings}')
    if not options.apply:
        print('Preview only. Use --apply to install this permission.')
        return
    # An explicit interpreter path prevents a workspace python.exe from being
    # selected. Arguments are deliberately not forwarded by the wrapper.
    wrapper.write_text('@echo off\n"' + sys.executable + '" "%~dp0backend\\list_workspace.py"\nexit /b %errorlevel%\n', encoding='utf-8')
    settings.parent.mkdir(parents=True, exist_ok=True)
    if original is not None and updated != data:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = settings.with_name(f'settings.agentguard-backup-{stamp}.json')
        with backup.open('xb') as stream:
            stream.write(original)
        print(f'Backup: {backup}')
    if updated != data:
        temporary = settings.with_name('settings.agentguard-pending.json')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(updated, stream, indent=2)
        # Abort rather than overwriting a concurrent settings change.
        if (settings.read_bytes() if settings.exists() else None) != original:
            temporary.unlink()
            raise RuntimeError('Settings changed during setup; run setup again')
        temporary.replace(settings)
    (root / 'data').mkdir(exist_ok=True)
    (root / 'data' / 'listing-access.json').write_text(json.dumps({
        'workspace': str(workspace), 'command': command, 'grant': grant,
    }, indent=2), encoding='utf-8')
    print('Installed. Restart AgentGuard and start a NEW CLI session before testing.')


if __name__ == '__main__':
    main()
