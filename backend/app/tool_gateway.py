"""Single strict entrypoint for custom-agent tools. Unknown tools fail closed."""
import asyncio
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import uuid
import time
from urllib.parse import urlsplit

from .command_boundary import checked_path
from .windows_sandbox import IsolationUnavailable
from . import config
from .command_boundary import protected_parts


def display_args(args):
    """Preserve targets; replace potentially sensitive bodies with length/digest."""
    if not isinstance(args, dict):
        return {'invalid_type': type(args).__name__}
    result = {}
    for key, value in args.items():
        if key in ('content', 'body'):
            encoded = str(value).encode('utf-8')
            result[key] = {'bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}
        else:
            result[key] = value
    return result


class NetworkBroker:
    """Exact origins pinned by operator to literal IPs; never resolves model input.

    No redirects, environment proxies, arbitrary headers, URL credentials or DNS.
    Worker network access is independently denied by zero AppContainer capabilities.
    """
    def __init__(self, destinations=None):
        self.destinations = destinations or {}

    def validate(self, args):
        if set(args) - {'url', 'method', 'body'} or not isinstance(args.get('url'), str):
            raise ValueError('HTTP requires url, optional method and body only')
        url = args['url']
        if len(url) > 2048 or any(ord(c) < 33 for c in url) or '\\' in url:
            raise ValueError('Invalid URL')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Invalid HTTP destination')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        host = parsed.hostname.lower()
        authority = f'[{host}]' if ':' in host else host
        origin = f'{parsed.scheme}://{authority}:{port}'
        target = self.destinations.get(origin)
        if not target:
            raise ValueError('Destination is not explicitly approved')
        ip = str(ipaddress.ip_address(target))
        if ipaddress.ip_address(ip).is_loopback and port in (8911, 8912, 11434, config.BACKEND_PORT):
            raise ValueError('AgentGuard control plane and inference ports are not tool destinations')
        method = args.get('method', 'GET')
        body = args.get('body', '')
        if method not in ('GET', 'POST') or not isinstance(body, str) or len(body.encode()) > 16384:
            raise ValueError('Invalid HTTP method/body')
        return {'url': url, 'method': method, 'body': body, 'origin': origin,
                'host': host, 'authority': authority, 'ip': ip, 'port': port,
                'target': parsed.path or '/', 'query': parsed.query, 'tls': parsed.scheme == 'https'}

    def execute(self, normalized):
        n = normalized
        connection = http.client.HTTPConnection(n['ip'], n['port'], timeout=5)
        try:
            connection.connect()
            if n['tls']:
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=n['host'])
            target = n['target'] + ('?' + n['query'] if n['query'] else '')
            connection.request(n['method'], target, body=n['body'].encode(),
                               headers={'Host': f"{n['authority']}:{n['port']}", 'Content-Type': 'text/plain'})
            response = connection.getresponse()
            deadline, chunks, total = time.monotonic() + 10, [], 0
            while total <= 65536:
                if time.monotonic() > deadline:
                    raise TimeoutError('HTTP response deadline exceeded')
                part = response.read1(min(8192, 65537 - total))
                if not part:
                    break
                chunks.append(part)
                total += len(part)
            data = b''.join(chunks)
            if 300 <= response.status < 400:
                raise ValueError('Redirects are not followed')
            if len(data) > 65536:
                raise ValueError('HTTP response exceeds output budget')
            return {'ok': True, 'result': {'status': response.status, 'text': data.decode('utf-8', errors='replace')}}
        finally:
            connection.close()


class ToolGateway:
    def __init__(self, policy, approvals, audit, runner, broadcast, network=None):
        self.policy, self.approvals, self.audit = policy, approvals, audit
        self.runner, self.broadcast = runner, broadcast
        self.network = network or NetworkBroker()
        self.lock = asyncio.Lock()

    async def run_worker(self, tool, args):
        # Cancellation must not release the gateway lock while its worker remains
        # alive. The launcher owns a bounded deadline and kills the entire job.
        task = asyncio.create_task(asyncio.to_thread(self.runner.execute, tool, args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    def normalize(self, tool, args):
        if not isinstance(args, dict):
            raise ValueError('Arguments must be an object')
        if tool in ('read_file', 'write_file', 'delete_file'):
            keys = {'path'} if tool in ('read_file', 'delete_file') else {'path', 'content'}
            if set(args) != keys:
                raise ValueError('Unexpected or missing file arguments')
            target = checked_path(self.policy.workspace, args['path'], must_exist=tool in ('read_file', 'delete_file'))
            normalized = {'path': str(target)}
            if tool == 'write_file':
                if not isinstance(args['content'], str) or len(args['content'].encode()) > 65536:
                    raise ValueError('Write content must be at most 64 KiB')
                if target.exists():
                    raise ValueError('Write tool creates new files only')
                normalized['content'] = args['content']
            policy_action = 'view_file' if tool == 'read_file' else ('delete_file' if tool == 'delete_file' else 'write_to_file')
            return normalized, policy_action, {'AbsolutePath': str(target)}
        if tool == 'list_directory':
            if set(args) - {'path'} or ('path' in args and not isinstance(args['path'], str)):
                raise ValueError('Directory listing accepts only an optional workspace-relative path')
            target = checked_path(self.policy.workspace, args.get('path') or '.', must_exist=True)
            if not target.is_dir():
                raise ValueError('The requested workspace path is not a directory')
            normalized = {'path': str(target)}
            # Trusted adapter metadata; ordinary explicit policy rules apply.
            return normalized, 'list_dir', {'Directory': str(target), '_agentguard_workspace_metadata': True}
        if tool == 'shell':
            if set(args) != {'command'} or not isinstance(args['command'], str):
                raise ValueError('Shell requires only a literal command')
            normalized = {'command': args['command'], 'cwd': str(self.policy.workspace)}
            return normalized, 'run_command', {'CommandLine': args['command'], 'Cwd': str(self.policy.workspace)}
        if tool == 'http_request':
            normalized = self.network.validate(args)
            return normalized, tool, {'url': normalized['url'], 'method': normalized['method']}
        raise ValueError('Unknown tool name')

    async def call(self, tool, args):
        async with self.lock:
            return await self._call(tool, args)

    async def _call(self, tool, args):
        call_id, ids = uuid.uuid4().hex, []
        async def record(event, payload, decision=None):
            row = self.audit.append(event, {'call_id': call_id, 'tool': tool, **payload}, decision)
            ids.append(row['id'])
            await self.broadcast({'type': 'security_event', 'data': row})
            return row
        await record('tool_requested', {'requested': display_args(args)})
        try:
            normalized, policy_tool, policy_args = self.normalize(tool, args)
        except (ValueError, OSError, TypeError, RuntimeError) as exc:
            row = await record('policy_eval', {'reason': str(exc), 'attribution': 'AGENTGUARD_POLICY_BLOCK'}, 'block')
            await self.broadcast({'type': 'action_issue', 'data': row})
            return {'ok': False, 'attribution': 'AGENTGUARD_POLICY_BLOCK', 'reason': str(exc), 'audit_ids': ids}
        decision, reason, rule = self.policy.evaluate(policy_tool, policy_args, broker_validated=tool == 'http_request')
        await record('policy_eval', {'normalized': display_args(normalized), 'reason': reason, 'rule_id': rule}, decision)
        if decision == 'ask':
            async def pending(rec):
                await record('approval_requested', rec, 'ask')
                await self.broadcast({'type': 'approval', 'data': rec})
            approval = await self.approvals.request(tool, display_args(normalized), reason, on_pending=pending)
            decision = approval['decision']
            if decision == 'block':
                reason = ('Approval timed out.' if approval.get('decided_by') == 'timeout'
                          else 'You blocked this action.') + ' Policy reason: ' + approval['reason']
            await record('approval_decided', approval, decision)
            await self.broadcast({'type': 'approval', 'data': approval})
        if decision == 'allow':
            try:
                # Never release stale targets or newly blocked policy after waiting.
                fresh, _, _ = self.normalize(tool, args)
                current, current_reason, _ = self.policy.evaluate(policy_tool, policy_args, broker_validated=tool == 'http_request')
                if fresh != normalized:
                    raise ValueError('Target or policy changed while awaiting approval')
                if current == 'block':
                    raise ValueError(current_reason)
            except (ValueError, OSError, RuntimeError) as exc:
                decision, reason = 'block', str(exc)
        if decision != 'allow':
            row = await record('execution_skipped', {'reason': reason, 'attribution': 'AGENTGUARD_POLICY_BLOCK'}, 'block')
            await self.broadcast({'type': 'action_issue', 'data': row})
            return {'ok': False, 'attribution': 'AGENTGUARD_POLICY_BLOCK', 'reason': reason, 'audit_ids': ids}
        try:
            if tool == 'http_request':
                probe = await self.run_worker('__probe', {})
                if not probe.get('ok'):
                    raise IsolationUnavailable('Worker readiness probe failed')
                result = await asyncio.to_thread(self.network.execute, normalized)
            else:
                result = await self.run_worker(tool, normalized)
            attribution = 'EXECUTED' if result.get('ok') else 'EXECUTION_FAILED'
            if (result.get('enforcement') or {}).get('timed_out'):
                attribution = 'OS_SANDBOX_BLOCK'
                await record('resource_limit', {'resource': 'wall_clock', 'attribution': attribution,
                                                'enforcement': result['enforcement']})
        except IsolationUnavailable as exc:
            result = {'ok': False, 'reason': str(exc)}
            attribution = 'NOT_TESTED'  # setup failure is not an OS attack block
        except (OSError, ValueError) as exc:
            result = {'ok': False, 'reason': str(exc)}
            attribution = 'EXECUTION_FAILED'  # DNS/transport failure is not NETWORK_BLOCK
        safe_result = result
        if tool == 'list_directory' and result.get('ok'):
            safe_result = {'ok': True, 'result': result.get('result'), 'enforcement': result.get('enforcement')}
        await record('execution_result', {'ok': safe_result.get('ok'), 'attribution': attribution,
                                          'reason': safe_result.get('reason'), 'enforcement': safe_result.get('enforcement'),
                                          'metadata': safe_result.get('result') if tool == 'list_directory' else None})
        return {**safe_result, 'attribution': attribution, 'audit_ids': ids}
