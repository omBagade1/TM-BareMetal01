"""Bounded, conservative source-file inspection, not a general injection detector."""
import re
from pathlib import Path

from .command_boundary import checked_path, EXECUTION_TOOLS

LIMIT = 64 * 1024


def inspect_read(workspace: Path, tool: str, args: dict) -> str | None:
    """Called only after path/command boundaries succeed; never execute source text."""
    cwd = workspace
    for key in ('Cwd', 'cwd', 'WorkingDirectory', 'working_directory'):
        if key in args:
            cwd = checked_path(workspace, args[key])
    paths = []
    if tool in ('view_file', 'read_file'):
        keys = ('AbsolutePath', 'FilePath', 'TargetFile', 'target_file', 'File', 'file',
                'Path', 'path', 'file_path')
        paths = [args[key] for key in keys if key in args]
    elif tool in EXECUTION_TOOLS:
        command = str(args.get('CommandLine') or args.get('command') or '')
        tokens = re.findall(r'''"[^"]*"|'[^']*'|[^\s'"]+''', command)
        if tokens and tokens[0].lower() == 'get-content':
            # command_boundary has already restricted this to one literal path.
            paths = [token.strip('\'"') for token in tokens[1:]
                     if token.lower() not in ('-raw', '-path', '-literalpath')]
    for value in paths:
        path = checked_path(workspace, value, cwd=cwd)
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            return 'Source read blocked: the file exceeds the 64 KiB content-inspection limit.'
        text = raw.decode('utf-8-sig', errors='replace')
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = raw.decode('utf-16', errors='replace')
        override = re.search(r'\bignore\b.{0,100}\b(task|instructions?|summary)\b', text, re.I | re.S)
        outside = re.search(r'\b(read|open|load)\b.{0,100}\.\.[/\\]', text, re.I | re.S)
        upload = (re.search(r'\b(send|upload|post|exfiltrate)\b', text, re.I)
                  and re.search(r'https?://', text, re.I))
        conceal = re.search(r'\b(hide|conceal)\b.{0,100}\b(user|step|action)', text, re.I | re.S)
        if outside and upload and (override or conceal):
            return ('Source read blocked by AgentGuard: suspected indirect prompt injection. '
                    'The file combines instructions to read a parent-relative file and send data '
                    'to an HTTP destination with instructions to override the task or conceal actions. '
                    'AgentGuard withheld the source from this tool call; no injected read or upload '
                    'was executed by this blocked call.')
    return None
