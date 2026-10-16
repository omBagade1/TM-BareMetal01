"""Private worker entrypoint; executes only inside the launcher's verified token/job."""
import json
import os
from pathlib import Path
import subprocess
import sys
import stat
import time


def protected_parts(parts):
    protected = {'.ssh', '.aws', '.azure', '.gemini', '.codex', '.agents', '.git',
                 'credentials', 'credentials.json', 'oauth_creds.json',
                 'id_rsa', 'id_ed25519', 'id_ecdsa'}
    for part in parts:
        name = part.lower().rstrip(' .')
        if (name in protected or name == '.env' or name.startswith('.env.')
                or name.endswith(('.env', '.pem', '.key', '.pfx', '.p12'))):
            return True
    return False


def require_isolation():
    import ctypes as C
    from ctypes import wintypes as W
    if os.name != 'nt':
        raise RuntimeError('Windows isolation required')
    kernel, advapi = C.WinDLL('kernel32'), C.WinDLL('advapi32')
    kernel.GetCurrentProcess.restype = W.HANDLE
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    kernel.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    token, flag, returned, member = W.HANDLE(), W.DWORD(), W.DWORD(), W.BOOL()
    process = kernel.GetCurrentProcess()
    if not advapi.OpenProcessToken(process, 0x8, C.byref(token)):
        raise RuntimeError('Cannot inspect worker token')
    try:
        if (not advapi.GetTokenInformation(token, 29, C.byref(flag), C.sizeof(flag), C.byref(returned))
                or flag.value != 1 or not kernel.IsProcessInJob(process, None, C.byref(member)) or not member.value):
            raise RuntimeError('Worker requires AppContainer and Job Object')
    finally:
        kernel.CloseHandle(token)


def run(call):
    tool, args = call['tool'], call['args']
    if tool == '__probe':
        return {'ready': True}
    if tool == 'read_file':
        with open(args['path'], 'rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError('File exceeds 64 KiB output budget')
        return {'text': data.decode('utf-8')}
    if tool == 'write_file':
        # Exclusive creation: no overwrites or link traversal at the final target.
        with open(args['path'], 'x', encoding='utf-8') as stream:
            stream.write(args['content'])
        return {'created': True, 'bytes': len(args['content'].encode('utf-8'))}
    if tool == 'delete_file':
        target = Path(args['path'])
        if not target.is_file():
            raise ValueError('Target is not a regular file')
        target.unlink()
        return {'deleted': True, 'path': str(target)}
    if tool == 'list_directory':
        root = Path(args['path'])
        files, directories, skipped, truncated = [], [], 0, False
        deadline = time.monotonic() + 2
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= 1000 or time.monotonic() > deadline:
                    truncated = True
                    break
                try:
                    info = entry.stat(follow_symlinks=False)
                    if (stat.S_ISLNK(info.st_mode)
                            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                            or protected_parts((entry.name,))):
                        skipped += 1
                        continue
                    if stat.S_ISREG(info.st_mode):
                        files.append({'name': entry.name, 'size_bytes': info.st_size})
                    elif stat.S_ISDIR(info.st_mode):
                        directories.append(entry.name)
                except OSError:
                    skipped += 1
        files.sort(key=lambda item: item['name'].casefold())
        directories.sort(key=str.casefold)
        return {'directory': str(root), 'files': files, 'directories': directories,
                'file_count': len(files), 'count_is_exact': not truncated,
                'skipped': skipped, 'truncated': truncated, 'entry_limit': 1000}
    if tool == 'shell':
        exe = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        # Spool bounded by parent's deadline/job memory; avoid unbounded PIPE buffers.
        output = Path(os.environ['TEMP']) / 'shell.txt'
        with output.open('wb') as stream:
            result = subprocess.run([exe, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', args['command']],
                                    cwd=args['cwd'], stdout=stream, stderr=subprocess.STDOUT, close_fds=True)
        with output.open('rb') as stream:
            text = stream.read(65536).decode('utf-8', errors='replace')
        return {'exit_code': result.returncode, 'text': text}
    raise ValueError('Unknown worker tool')


if __name__ == '__main__':
    # Fail before touching request/result files when invoked outside the launcher.
    require_isolation()
    try:
        result = {'ok': True, 'result': run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))}
    except Exception as exc:
        result = {'ok': False, 'error_type': type(exc).__name__, 'error': str(exc)[:1000]}
    Path(sys.argv[2]).write_text(json.dumps(result), encoding='utf-8')
