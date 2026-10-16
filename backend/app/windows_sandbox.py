"""Windows AppContainer launcher. No ambient-token or subprocess fallback.

The operator must provision the profile and ACLs explicitly. Job Objects provide
resource control, not filesystem isolation. See docs/windows-security.md.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import stat
import time
import uuid
from contextlib import contextmanager

PROFILE = 'AgentGuard.Worker.v1'


def profile_name(workspace):
    identity = os.path.normcase(str(Path(workspace).resolve()))
    return PROFILE + '.' + hashlib.sha256(identity.encode()).hexdigest()[:24]


def control_directory(workspace):
    root = Path(workspace).resolve()
    return root.parent / ('.agentguard-control-' + profile_name(root).rsplit('.', 1)[1])


class IsolationUnavailable(RuntimeError):
    pass


def workspace_sid_string(workspace):
    userenv = C.WinDLL('userenv', use_last_error=True)
    advapi = C.WinDLL('advapi32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes, derive.restype = [W.LPCWSTR, C.POINTER(C.c_void_p)], C.c_long
    convert = advapi.ConvertSidToStringSidW
    convert.argtypes, convert.restype = [C.c_void_p, C.POINTER(W.LPWSTR)], W.BOOL
    advapi.FreeSid.argtypes, advapi.FreeSid.restype = [C.c_void_p], C.c_void_p
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [C.c_void_p], C.c_void_p
    sid, string = C.c_void_p(), W.LPWSTR()
    try:
        if derive(profile_name(workspace), C.byref(sid)) != 0:
            raise IsolationUnavailable('Cannot derive workspace SID for temporary directory')
        if not convert(sid, C.byref(string)):
            raise IsolationUnavailable(f'Cannot convert workspace SID: {C.WinError(C.get_last_error())}')
        return string.value
    finally:
        if string:
            kernel.LocalFree(C.cast(string, C.c_void_p))
        if sid:
            advapi.FreeSid(sid)


@contextmanager
def worker_call_directory(workspace):
    control = control_directory(workspace)
    if (not control.is_dir() or control.is_symlink()
            or getattr(control.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise IsolationUnavailable('Run explicit Windows sandbox setup; control directory is absent')
    sid = workspace_sid_string(workspace)
    with tempfile.TemporaryDirectory(prefix='call-', dir=control) as tmp:
        # Python's Windows mode 0700 removes inherited package ACEs. Keep its
        # private owner/system/admin ACL and grant only this workspace package.
        target = Path(tmp)
        if target.resolve().parent != control.resolve() or target.is_symlink():
            raise IsolationUnavailable('Unexpected worker temporary directory')
        icacls = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icacls.exe'
        result = subprocess.run([str(icacls), str(target), '/grant', f'*{sid}:(OI)(CI)(M)'],
                                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise IsolationUnavailable(f'Worker temporary-directory ACL failed: {(result.stderr or result.stdout)[:1000]}')
        yield target


# A fixed bootstrap, never model-supplied code. No handles are inherited. Python
# startup before -c may still fail without diagnostics; report its exit separately.
WORKER_BOOTSTRAP = '''import sys
class BoundedStderr:
    def __init__(self, path):
        self.stream = open(path, 'x', encoding='utf-8')
        self.remaining = 8192
    def write(self, text):
        part = str(text)[:self.remaining]
        self.remaining -= len(part)
        self.stream.write(part)
        self.stream.flush()
        return len(text)
    def flush(self):
        self.stream.flush()
sys.stderr = BoundedStderr(sys.argv[4])
sys.argv = sys.argv[1:4]
with open(sys.argv[0], 'rb') as source:
    code = compile(source.read(), sys.argv[0], 'exec')
exec(code, {'__name__': '__main__', '__file__': sys.argv[0]})
'''


def worker_diagnostic(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            return 'No safe startup diagnostic available'
        with path.open('rb') as stream:
            return stream.read(8192).decode('utf-8', errors='replace').strip()
    except OSError:
        return 'No startup diagnostic available'


def worker_environment(temporary, profile_folder):
    """Explicit Windows bootstrap variables; never copy the backend environment.

    AppContainer startup redirects profile-related environment entries. Supply
    those entries using only its own registered storage, not the host user profile.
    """
    system = os.environ.get('SystemRoot', r'C:\Windows')
    return {'SystemRoot': system, 'WINDIR': system,
            'LOCALAPPDATA': str(profile_folder), 'APPDATA': str(profile_folder),
            'USERPROFILE': str(profile_folder), 'TEMP': str(temporary), 'TMP': str(temporary)}


def registered_profile_folder(sid):
    """Read the profile registered for this account; do not create or repair it."""
    advapi = C.WinDLL('advapi32', use_last_error=True)
    userenv = C.WinDLL('userenv', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    ole = C.WinDLL('ole32')
    convert = advapi.ConvertSidToStringSidW
    convert.argtypes, convert.restype = [C.c_void_p, C.POINTER(W.LPWSTR)], W.BOOL
    folder = userenv.GetAppContainerFolderPath
    folder.argtypes, folder.restype = [W.LPCWSTR, C.POINTER(W.LPWSTR)], C.c_long
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [C.c_void_p], C.c_void_p
    ole.CoTaskMemFree.argtypes, ole.CoTaskMemFree.restype = [C.c_void_p], None
    sid_text, path_text = W.LPWSTR(), W.LPWSTR()
    try:
        if not convert(sid, C.byref(sid_text)):
            raise IsolationUnavailable(f'ConvertSidToStringSidW: {C.WinError(C.get_last_error())}')
        result = folder(sid_text.value, C.byref(path_text))
        if result != 0:
            raise IsolationUnavailable(
                f'GetAppContainerFolderPath failed (HRESULT 0x{result & 0xffffffff:08x}). '
                'The workspace AppContainer profile is unavailable to this Windows account. '
                'Use the same normal Windows account for setup and the backend.')
        path = Path(path_text.value)
        if not path.is_absolute() or not path.is_dir():
            raise IsolationUnavailable('Registered AppContainer profile folder is unavailable')
        return path
    finally:
        if path_text:
            ole.CoTaskMemFree(C.cast(path_text, C.c_void_p))
        if sid_text:
            kernel.LocalFree(C.cast(sid_text, C.c_void_p))


class WindowsSandbox:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.last_evidence = None

    def status(self):
        return {'boundary': 'AppContainer (zero capabilities) + Job Object',
                'state': 'UNVERIFIED' if self.last_evidence is None else 'PARTIAL',
                'last_launch': self.last_evidence,
                'network': 'zero worker capabilities; live IPv4/IPv6/DNS probes required',
                'setup_required': True,
                'legacy_adapters_isolated': False}

    def execute(self, tool, args):
        if os.name != 'nt':
            raise IsolationUnavailable('Windows 10/11 is required')
        # The control directory is NOT inside the model-visible workspace.
        control = control_directory(self.workspace)
        if (not control.is_dir() or control.is_symlink()
                or getattr(control.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise IsolationUnavailable('Run explicit Windows sandbox setup; control directory is absent')
        with worker_call_directory(self.workspace) as tmp:
            request = Path(tmp) / 'request.json'
            response = Path(tmp) / 'response.json'
            diagnostic = Path(tmp) / 'startup-error.txt'
            request.write_text(json.dumps({'tool': tool, 'args': args}), encoding='utf-8')
            worker = Path(__file__).with_name('sandbox_worker.py')
            evidence = launch([sys.executable, '-I', '-B', '-c', WORKER_BOOTSTRAP,
                               str(worker), str(request), str(response), str(diagnostic)],
                              self.workspace, Path(tmp))
            self.last_evidence = evidence
            if evidence['timed_out']:
                return {'ok': False, 'reason': 'Worker wall-clock deadline; entire Job Object terminated',
                        'enforcement': evidence}
            for part in (response, *response.parents):
                if part.exists():
                    info = part.lstat()
                    if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise IsolationUnavailable('Reparse point in worker result path')
            if not response.is_file() or response.stat().st_size > 131072:
                raise IsolationUnavailable(f'Worker produced no bounded result; exit={evidence["exit_code"]}. '
                                           f'Startup diagnostic: {worker_diagnostic(diagnostic)}')
            if response.stat().st_nlink != 1 or evidence['exit_code'] != 0:
                raise IsolationUnavailable('Untrusted worker result or abnormal exit')
            result = json.loads(response.read_text(encoding='utf-8'))
            if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                raise IsolationUnavailable('Malformed worker result')
            result['enforcement'] = evidence
            return result


def launch(argv, cwd, temporary, *, seconds=15, memory_mb=256, processes=4, cpu_percent=20):
    """Trusted launcher; never exposed as a model tool. Starts suspended, no handles inherited."""
    if os.name != 'nt':
        raise IsolationUnavailable('Windows required')
    if not (1 <= seconds <= 60 and 32 <= memory_mb <= 512 and 1 <= processes <= 8 and 1 <= cpu_percent <= 50):
        raise ValueError('Invalid resource budget')
    k = C.WinDLL('kernel32', use_last_error=True)
    a = C.WinDLL('advapi32', use_last_error=True)
    u = C.WinDLL('userenv', use_last_error=True)
    ptr = C.c_void_p
    size = C.c_size_t

    class SI(C.Structure):
        _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                    ('x', W.DWORD), ('y', W.DWORD), ('xs', W.DWORD), ('ys', W.DWORD),
                    ('xc', W.DWORD), ('yc', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                    ('show', W.WORD), ('reserved2size', W.WORD), ('reserved2', ptr),
                    ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]
    class SIX(C.Structure):
        _fields_ = [('si', SI), ('attributes', ptr)]
    class PI(C.Structure):
        _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]
    class CAP(C.Structure):
        _fields_ = [('sid', ptr), ('capabilities', ptr), ('count', W.DWORD), ('reserved', W.DWORD)]
    class BASIC(C.Structure):
        _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64), ('flags', W.DWORD),
                    ('min_ws', size), ('max_ws', size), ('active', W.DWORD), ('affinity', size),
                    ('priority', W.DWORD), ('scheduling', W.DWORD)]
    class IO(C.Structure):
        _fields_ = [(name, C.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read', 'write', 'other')]
    class LIMITS(C.Structure):
        _fields_ = [('basic', BASIC), ('io', IO), ('process_memory', size), ('job_memory', size),
                    ('peak_process', size), ('peak_job', size)]
    class CPU(C.Structure):
        _fields_ = [('flags', W.DWORD), ('rate', W.DWORD)]
    class ACCOUNTING(C.Structure):
        _fields_ = [('user', C.c_int64), ('kernel', C.c_int64), ('period_user', C.c_int64),
                    ('period_kernel', C.c_int64), ('faults', W.DWORD), ('total', W.DWORD),
                    ('active', W.DWORD), ('terminated', W.DWORD)]

    def bind(dll, name, arguments, result=W.BOOL):
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = arguments, result
        return fn
    create_job = bind(k, 'CreateJobObjectW', [ptr, W.LPCWSTR], W.HANDLE)
    set_job = bind(k, 'SetInformationJobObject', [W.HANDLE, C.c_int, ptr, W.DWORD])
    query_job = bind(k, 'QueryInformationJobObject', [W.HANDLE, C.c_int, ptr, W.DWORD, ptr])
    assign = bind(k, 'AssignProcessToJobObject', [W.HANDLE, W.HANDLE])
    close = bind(k, 'CloseHandle', [W.HANDLE])
    terminate = bind(k, 'TerminateJobObject', [W.HANDLE, W.UINT])
    kill = bind(k, 'TerminateProcess', [W.HANDLE, W.UINT])
    derive = bind(u, 'DeriveAppContainerSidFromAppContainerName', [W.LPCWSTR, C.POINTER(ptr)], C.c_long)
    free_sid = bind(a, 'FreeSid', [ptr], ptr)
    init = bind(k, 'InitializeProcThreadAttributeList', [ptr, W.DWORD, W.DWORD, C.POINTER(size)])
    update = bind(k, 'UpdateProcThreadAttribute', [ptr, W.DWORD, size, ptr, size, ptr, ptr])
    delete = bind(k, 'DeleteProcThreadAttributeList', [ptr], None)
    create = bind(k, 'CreateProcessW', [W.LPCWSTR, W.LPWSTR, ptr, ptr, W.BOOL, W.DWORD, ptr, W.LPCWSTR, ptr, ptr])
    open_token = bind(a, 'OpenProcessToken', [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)])
    token_info = bind(a, 'GetTokenInformation', [W.HANDLE, C.c_int, ptr, W.DWORD, C.POINTER(W.DWORD)])
    equal_sid = bind(a, 'EqualSid', [ptr, ptr])
    in_job = bind(k, 'IsProcessInJob', [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)])
    resume = bind(k, 'ResumeThread', [W.HANDLE], W.DWORD)
    wait = bind(k, 'WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD)
    exit_code = bind(k, 'GetExitCodeProcess', [W.HANDLE, C.POINTER(W.DWORD)])
    def check(ok, stage='Windows API'):
        if not ok:
            raise IsolationUnavailable(f'{stage}: {C.WinError(C.get_last_error())}')

    sid, token, pi = ptr(), W.HANDLE(), PI()
    job, attributes = None, None
    try:
        if derive(profile_name(cwd), C.byref(sid)) != 0:
            raise IsolationUnavailable('Cannot derive AppContainer SID')
        profile_folder = registered_profile_folder(sid)
        job = create_job(None, None)
        check(job)
        limits = LIMITS()
        # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS | PROCESS_MEMORY | JOB_MEMORY.
        # No breakaway flags. Every descendant stays in this job.
        limits.basic.flags = 0x2000 | 0x8 | 0x100 | 0x200
        limits.basic.active = processes
        limits.process_memory = limits.job_memory = memory_mb * 1024 * 1024
        check(set_job(job, 9, C.byref(limits), C.sizeof(limits)))
        cpu = CPU(0x1 | 0x4, cpu_percent * 100)  # ENABLE | HARD_CAP
        check(set_job(job, 15, C.byref(cpu), C.sizeof(cpu)))
        effective, effective_cpu = LIMITS(), CPU()
        check(query_job(job, 9, C.byref(effective), C.sizeof(effective), None))
        check(query_job(job, 15, C.byref(effective_cpu), C.sizeof(effective_cpu), None))
        if (effective.basic.flags & limits.basic.flags != limits.basic.flags
                or effective.basic.active != processes or effective.job_memory != limits.job_memory
                or effective.process_memory != limits.process_memory
                or effective_cpu.flags != cpu.flags or effective_cpu.rate != cpu.rate):
            raise IsolationUnavailable('Effective job limits differ from requested limits')
        needed = size()
        init(None, 1, 0, C.byref(needed))
        attributes = C.create_string_buffer(needed.value)
        check(init(attributes, 1, 0, C.byref(needed)))
        caps = CAP(sid, None, 0, 0)
        check(update(attributes, 0, 0x20009, C.byref(caps), C.sizeof(caps), None, None))
        startup = SIX()
        startup.si.cb = C.sizeof(startup)
        startup.attributes = C.cast(attributes, ptr)
        # Only these environment entries cross the boundary; no tokens, proxies,
        # Python path, provider settings, or inherited backend hook secrets.
        env = worker_environment(temporary, profile_folder)
        environment = C.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items(), key=lambda item: item[0].upper())) + '\0\0')
        command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
        check(create(argv[0], command, None, None, False,
                     0x4 | 0x80000 | 0x400 | 0x08000000, environment, str(cwd), C.byref(startup), C.byref(pi)),
              'CreateProcessW (AppContainer, suspended, explicit environment)')
        check(assign(job, pi.process), 'AssignProcessToJobObject')
        check(open_token(pi.process, 0x8, C.byref(token)), 'OpenProcessToken')
        flag, returned = W.DWORD(), W.DWORD()
        check(token_info(token, 29, C.byref(flag), C.sizeof(flag), C.byref(returned)))
        if flag.value != 1:
            raise IsolationUnavailable('Effective token is not AppContainer')
        check(token_info(token, 20, C.byref(flag), C.sizeof(flag), C.byref(returned)))
        if flag.value != 0:
            raise IsolationUnavailable('Worker token is elevated')
        token_info(token, 30, None, 0, C.byref(returned))
        capabilities = C.create_string_buffer(returned.value)
        check(token_info(token, 30, capabilities, returned.value, C.byref(returned)))
        if C.cast(capabilities, C.POINTER(W.DWORD))[0] != 0:
            raise IsolationUnavailable('Worker unexpectedly has capabilities')
        token_info(token, 31, None, 0, C.byref(returned))
        sid_buffer = C.create_string_buffer(returned.value)
        check(token_info(token, 31, sid_buffer, returned.value, C.byref(returned)))
        token_sid = C.cast(sid_buffer, C.POINTER(ptr))[0]
        check(equal_sid(sid, token_sid))
        member = W.BOOL()
        check(in_job(pi.process, job, C.byref(member)))
        check(member.value)
        if resume(pi.thread) == 0xFFFFFFFF:
            check(False)
        timed_out = wait(pi.process, seconds * 1000) == 0x102
        if timed_out:
            check(terminate(job, 1460))
            check(wait(pi.process, 5000) == 0)
        code = W.DWORD()
        check(exit_code(pi.process, C.byref(code)))
        check(terminate(job, 1))  # kill surviving descendants even after normal parent exit
        deadline = time.monotonic() + 5
        while True:
            accounting = ACCOUNTING()
            check(query_job(job, 1, C.byref(accounting), C.sizeof(accounting), None))
            if accounting.active == 0:
                break
            if time.monotonic() >= deadline:
                raise IsolationUnavailable('Job descendants did not terminate within cleanup deadline')
            time.sleep(.01)
        return {'launch_id': uuid.uuid4().hex, 'pid': pi.pid, 'appcontainer': True,
                'profile_sid_verified': True, 'job_membership_verified': True,
                'elevated': False, 'effective_job_limits_verified': True,
                'active_processes_after_cleanup': 0,
                'inherited_handles': False, 'network_capabilities': 0,
                'memory_mb': memory_mb, 'process_limit': processes, 'cpu_percent': cpu_percent,
                'deadline_seconds': seconds, 'timed_out': timed_out, 'exit_code': code.value}
    finally:
        if job:
            terminate(job, 1)
        if pi.process:
            kill(pi.process, 1)  # also covers failure before job assignment
        for handle in (token, pi.thread, pi.process, job):
            if handle:
                close(handle)
        if attributes:
            delete(attributes)
        if sid:
            free_sid(sid)
