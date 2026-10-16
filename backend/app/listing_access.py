"""Configuration for the narrowly granted CLI metadata helper."""
import json
from pathlib import Path


def load_listing_access(data_dir: Path, workspace: Path) -> dict | None:
    try:
        data = json.loads((data_dir / 'listing-access.json').read_text(encoding='utf-8'))
        if Path(data['workspace']).resolve(strict=True) != workspace.resolve(strict=True):
            return None
        if Path(__file__).resolve().parents[2].is_relative_to(workspace.resolve(strict=True)):
            return None
        command = data['command']
        expected = (Path(__file__).resolve().parents[2] / 'list-workspace.cmd').as_posix()
        if command != expected or not Path(command).is_file():
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def is_listing_command(command: str, access: dict) -> bool:
    return command.strip() == access['command']


def listing_guidance(data_dir: Path, workspace: Path, cwd: str) -> str:
    access = load_listing_access(data_dir, workspace)
    if not access or Path(cwd).resolve() != workspace.resolve():
        return ''
    return (
        '[AgentGuard workspace capability]\n'
        'For listing file names or sizes in the current workspace root, use run_command '
        f'with this exact CommandLine: {access["command"]}\n'
        f'Set Cwd to {workspace.resolve()}. Use no additional arguments, pipelines, or shell wrappers. '
        'This read-only helper returns JSON containing actual immediate file names and sizes. '
        'Report the returned data to the user. It does not read file contents or list other directories. '
        'Do not use it for an outside-workspace request or as a retry of a denied action. '
        'For unrelated tasks, use the usual tools.\n\n'
    )
