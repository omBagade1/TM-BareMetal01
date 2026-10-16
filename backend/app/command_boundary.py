"""Conservative command eligibility checks, not an operating-system sandbox.

Only a small literal PowerShell read/list grammar is eligible for policy review.
Unknown syntax is denied, never guessed safe from keywords or model judgments.
"""
import os
from pathlib import Path
import re
import stat
import time

EXECUTION_TOOLS = {'run_command', 'run_shell_command', 'execute_command', 'shell',
                   'bash', 'powershell', 'execute_code', 'run_python', 'run_terminal_command'}
PROTECTED_PARTS = {'.ssh', '.aws', '.azure', '.gemini', '.codex', '.agents', '.git'}
PROTECTED_NAMES = {'credentials', 'credentials.json', 'oauth_creds.json',
                   'id_rsa', 'id_ed25519', 'id_ecdsa'}


def protected_parts(parts) -> bool:
    for part in parts:
        name = part.lower().rstrip(' .')
        if (name in PROTECTED_PARTS or name in PROTECTED_NAMES or name == '.env'
                or name.startswith('.env.') or name.endswith(('.env', '.pem', '.key', '.pfx', '.p12'))):
            return True
    return False


def checked_path(root: Path, value: str, cwd: Path | None = None, must_exist=False) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonempty literal filesystem path is required.')
    if any(c in value for c in '\x00\r\n*?[]%~'):
        raise ValueError('Wildcards, expansions, and ambiguous paths are not eligible for approval.')
    # Exclude UNC/device paths, PowerShell providers, drive-relative paths, ADS.
    value = value.replace('\\', os.sep)
    if value.startswith('//') or value.startswith('\\\\'):
        raise ValueError('Network and device paths are blocked.')
    if ':' in value and not (os.name == 'nt' and re.match(r'^[A-Za-z]:[/\\]', value) and ':' not in value[2:]):
        raise ValueError('Provider paths and alternate data streams are blocked.')
    root = root.resolve()
    path = Path(value)
    if not path.is_absolute():
        path = (cwd or root) / path
    # Reject links/reparse points along the lexical route, before resolving.
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Links and reparse points are not eligible for approval.')
    target = path.resolve(strict=must_exist)
    if not target.is_relative_to(root):
        raise ValueError('Path is outside the approved workspace.')
    if protected_parts(target.relative_to(root).parts):
        raise ValueError('Credential, environment, or control files are protected.')
    if target.is_file() and target.stat().st_nlink > 1:
        raise ValueError('Files with multiple hard links are not eligible for approval.')
    return target


def check_listing_tree(target: Path, depth: int) -> None:
    """Bound metadata inspection and reject links before approving recursion."""
    pending = [(target, 0)]
    count = 0
    deadline = time.monotonic() + 2
    while pending:
        directory, level = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > 2000 or time.monotonic() > deadline:
                    raise ValueError('Directory listing is too large; choose a narrower workspace folder.')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Recursive listing contains a link or reparse point; choose a narrower folder.')
                if stat.S_ISDIR(info.st_mode) and level < depth:
                    pending.append((Path(entry.path), level + 1))


def command_boundary(workspace: Path, args: dict) -> str | None:
    """Return a block reason, or None when the limited command can be reviewed."""
    command = args.get('CommandLine', args.get('command'))
    if not isinstance(command, str) or not command.strip() or len(command) > 4096:
        return 'A supported literal command is required.'
    if 'CommandLine' in args and 'command' in args and args['CommandLine'] != args['command']:
        return 'Conflicting command arguments are blocked.'
    if any(args.get(key) for key in ('BypassSandbox', 'IsDaemon', 'RunPersistent', 'RequestedTerminalID')):
        return 'Sandbox bypass and persistent terminal execution are blocked.'
    # Recognize one fixed, data-only projection before parsing the source.
    # This does not authorize general pipelines or expression properties.
    if '|' in command:
        projection = re.fullmatch(
            r"(Get-ChildItem(?:[ \t]+[^|\r\n]+)?)[ \t]*\|[ \t]*"
            r"Select-Object[ \t]+(?:(?:-Property|-ExpandProperty)[ \t]+)?Name[ \t]*",
            command.strip(), re.IGNORECASE,
        )
        if not projection:
            return ('Unsupported pipeline. For folder names use Get-ChildItem -Directory -Name '
                    'with a literal workspace path, or pipe that listing only to Select-Object Name.')
        command = projection.group(1).strip()
    # This is intentionally not a general PowerShell parser. Operators,
    # substitutions, comments, escapes and executable wrappers never enter it.
    if re.search(r'[^A-Za-z0-9_ .:/\\\-\'\"]', command):
        return 'Shell operators, substitutions, or unsupported syntax are blocked.'
    tokens = re.findall(r'''"[^"]*"|'[^']*'|[^\s'"]+''', command)
    if ' '.join(tokens) != ' '.join(command.split()):
        return 'Malformed or concatenated shell arguments are blocked.'
    operation = tokens[0].lower() if tokens else ''
    if operation not in ('get-childitem', 'get-content', 'get-location', 'pwd', 'remove-item', 'del', 'rm'):
        return 'Unsupported command. Literal Get-ChildItem, Get-Content, Get-Location, pwd, and workspace file deletion can be reviewed; use workspace file tools for other work.'
    try:
        cwd_value = args.get('Cwd', args.get('cwd'))
        if not isinstance(cwd_value, str) or not os.path.isabs(cwd_value):
            return 'Command working directory must be an explicit absolute workspace directory.'
        cwd = checked_path(workspace, cwd_value, must_exist=True)
        if not cwd.is_dir():
            return 'Command working directory must be a directory.'
        if operation in ('get-location', 'pwd'):
            return None if len(tokens) == 1 else 'Get-Location and pwd do not accept arguments in this policy.'
        path = None
        depth = None
        recurse = False
        seen_flags = set()
        flags = {'-force', '-name', '-file', '-directory'} if operation == 'get-childitem' else ({'-raw'} if operation == 'get-content' else {'-force'})
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token.lower() in flags:
                seen_flags.add(token.lower())
                index += 1
                continue
            if operation == 'get-childitem' and token.lower() == '-recurse':
                recurse = True
                index += 1
                continue
            if operation == 'get-childitem' and token.lower() == '-depth':
                index += 1
                if depth is not None or index >= len(tokens) or tokens[index] not in ('0', '1', '2', '3'):
                    return 'Directory listing requires one literal -Depth from 0 to 3.'
                depth = int(tokens[index])
                index += 1
                continue
            if token.lower() in ('-path', '-literalpath'):
                index += 1
                if index >= len(tokens):
                    return 'The path parameter requires a literal value.'
                token = tokens[index]
            elif token.startswith('-'):
                if operation in ('remove-item', 'del', 'rm'):
                    return 'Unsupported command option. File deletion supports only a single literal regular file and optional -Force.'
                return 'Unsupported command option. Recursive directory listings require -Directory and -Depth 0 to 3; dynamic parameters are blocked.'
            if path is not None:
                return 'Only one literal target path is supported.'
            path = token[1:-1] if token[:1] in ("'", '"') else token
            if not path or path.startswith('-'):
                return 'Invalid literal target path.'
            index += 1
        if path is None and operation in ('get-content', 'remove-item', 'del', 'rm'):
            return f'{operation} requires a literal workspace file.'
        target = checked_path(workspace, path or '.', cwd=cwd, must_exist=True)
        if operation == 'get-content' and not target.is_file():
            return 'Get-Content can only read a regular workspace file.'
        if operation in ('remove-item', 'del', 'rm') and not target.is_file():
            return 'File deletion can only remove an existing regular workspace file.'
        if recurse or depth is not None:
            if depth is None or '-directory' not in seen_flags or '-file' in seen_flags:
                return 'Recursive listing requires -Directory and an explicit -Depth from 0 to 3.'
            if not target.is_dir():
                return 'Recursive listing requires an existing workspace directory.'
            check_listing_tree(target, depth)
    except (ValueError, OSError, RuntimeError) as exc:
        return str(exc)
    return None
