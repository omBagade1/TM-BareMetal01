"""CLI-callable fixed workspace metadata helper. Never accepts a target path."""
import json
import sys
from pathlib import Path

from app.workspace_files import list_workspace_files


def main():
    if len(sys.argv) != 1:
        raise ValueError('This helper accepts no arguments')
    root = Path(__file__).resolve().parent.parent
    access = json.loads((root / 'data' / 'listing-access.json').read_text(encoding='utf-8'))
    workspace = Path(access['workspace'])
    # Detect a root replaced by a junction after setup. No inherited environment
    # variables can change the target of this helper.
    if workspace.resolve(strict=True) != workspace:
        raise ValueError('The configured workspace location has changed')
    print(json.dumps(list_workspace_files(workspace, str(workspace)), ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print(f'Workspace listing failed: {exc}', file=sys.stderr)
        sys.exit(1)
