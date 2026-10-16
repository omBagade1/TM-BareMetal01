"""Explicit operator setup. No elevation, firewall edits, or recursive ACL replacement.

Run --plan first. --apply creates an AppContainer profile and adds narrowly scoped
ACL entries. Existing ACLs are preserved. Do not run against a secrets directory.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import sys
from app.windows_sandbox import profile_name, control_directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--audit-dir', type=Path, default=Path(__file__).resolve().parent.parent / 'data')
    args = parser.parse_args()
    root = args.workspace.resolve()
    if os.name != 'nt':
        parser.error('Windows 10/11 required')
    if root == Path(root.anchor) or root == Path.home() or root == Path(__file__).resolve().parent.parent:
        parser.error('Choose a dedicated disposable workspace, never a profile or repository root')
    if not root.is_dir() or any(p.is_symlink() or (p.exists() and p.stat().st_file_attributes & 0x400)
                                for p in (root, *root.parents)):
        parser.error('Workspace must exist without reparse points')
    control = control_directory(root)
    audit_dir = args.audit_dir.resolve()
    if audit_dir.is_relative_to(root):
        parser.error('Audit directory must be outside the sandbox workspace')
    profile = profile_name(root)
    worker = Path(__file__).resolve().parent / 'app/sandbox_worker.py'
    for candidate in (control, audit_dir, *(root / name for name in ('.agents', '.git', '.aws', '.gemini', '.codex'))):
        for part in (candidate, *candidate.parents):
            if part.exists() and (not part.is_dir() or part.lstat().st_file_attributes & 0x400):
                parser.error(f'Refusing setup through non-directory or reparse point: {part}')
    print(f'Profile: {profile}\nWorkspace modify: {root}\nControl modify: {control}\nWorker read: {worker}')
    print(f'Explicit audit-directory denial for this SID: {audit_dir}')
    print('Python runtime must already be readable by AppContainer. No global/runtime ACL will be changed.')
    if not args.apply:
        print('Plan only. Re-run with --apply to provision under the normal operator account.')
        return
    userenv, advapi, kernel = C.WinDLL('userenv'), C.WinDLL('advapi32'), C.WinDLL('kernel32')
    sid = C.c_void_p()
    create = userenv.CreateAppContainerProfile
    create.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)]
    create.restype = C.c_long
    hr = create(profile, 'AgentGuard worker', 'Network-denied AgentGuard worker', None, 0, C.byref(sid))
    if hr != 0:
        if hr & 0xffffffff != 0x800700b7:
            raise OSError(f'CreateAppContainerProfile failed: 0x{hr & 0xffffffff:08x}; no fallback')
        derive = userenv.DeriveAppContainerSidFromAppContainerName
        derive.argtypes = [W.LPCWSTR, C.POINTER(C.c_void_p)]
        derive.restype = C.c_long
        if derive(profile, C.byref(sid)) != 0:
            raise OSError('Cannot derive existing profile SID')
    string = W.LPWSTR()
    advapi.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    if not advapi.ConvertSidToStringSidW(sid, C.byref(string)):
        raise OSError('SID conversion failed')
    sid_text = string.value
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree(C.cast(string, C.c_void_p))
    advapi.FreeSid.argtypes = [C.c_void_p]
    advapi.FreeSid(sid)
    control.mkdir(exist_ok=True)
    for target in (root, control):
        subprocess.run(['icacls.exe', str(target), '/grant', f'*{sid_text}:(OI)(CI)(M)'], check=True)
        subprocess.run(['icacls.exe', str(target), '/setintegritylevel', '(OI)(CI)L'], check=True)
    subprocess.run(['icacls.exe', str(worker), '/grant', f'*{sid_text}:(R)'], check=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(['icacls.exe', str(audit_dir), '/deny', f'*{sid_text}:(OI)(CI)(F)'], check=True)
    for name in ('.agents', '.git', '.aws', '.gemini', '.codex'):
        protected = root / name
        protected.mkdir(exist_ok=True)
        subprocess.run(['icacls.exe', str(protected), '/deny', f'*{sid_text}:(OI)(CI)(F)'], check=True)
    print(f'Provisioned SID {sid_text}. Run isolation tests; this is not a verification result.')


if __name__ == '__main__':
    main()
