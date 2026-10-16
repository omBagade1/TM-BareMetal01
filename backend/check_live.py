"""Local smoke check; only approves reading workspace/test.txt."""
import asyncio
import json
import os
from pathlib import Path

import httpx
import websockets


async def main():
    base = os.environ.get("AGENTGUARD_CHECK_URL", "http://127.0.0.1:8911")
    async with httpx.AsyncClient(base_url=base, timeout=20) as client:
        assert (await client.get("/api/health")).json()["ok"]
        status = (await client.get("/api/status")).json()
        assert status["session"]["state"] != "running", "Stop the existing session before the smoke check"
        workspace = Path(status["workspace"])
        response = await client.post("/api/policy/evaluate", json={"tool":"view_file", "args":{"AbsolutePath":str(workspace.parent / 'outside.txt')}})
        assert response.json()["decision"] == "block", response.text
        assert (await client.get('/api/status', headers={'Origin':'https://untrusted.example'})).status_code == 403
        async with websockets.connect(base.replace('http', 'ws')+'/ws', origin=base) as ws:
            assert json.loads(await ws.recv())["type"] == "status"
            await ws.send(json.dumps({"type":"ping"}))
            assert json.loads(await ws.recv())["type"] == "pong"
            result = await client.post('/api/session/start',json={"cwd":str(workspace)})
            result.raise_for_status()
            try:
                result = await client.post('/api/session/message',json={"content":"Read only test.txt in the current workspace and quote its contents. Do not modify files or run commands."})
                result.raise_for_status()
                saw_result = False
                async with asyncio.timeout(90):
                    while True:
                        event = json.loads(await ws.recv())
                        if event['type'] == 'approval' and not event['data'].get('decision'):
                            rec = event['data']
                            requested = rec.get('args', {}).get('AbsolutePath', '')
                            allowed = rec['tool'] == 'view_file' and Path(requested).resolve() == (workspace / 'test.txt').resolve()
                            choice = 'allow' if allowed else 'block'
                            response = await client.post('/api/approvals/'+rec['id'],json={'decision':choice})
                            if response.status_code == 404:
                                continue  # Another connected reviewer already resolved it.
                            response.raise_for_status()
                            print('Approval:', rec['tool'], choice)
                        if event['type']=='event' and event['data'].get('event')=='result':
                            payload = event['data']['payload']
                            print('CLI result:', json.dumps(payload)[:1200])
                            saw_result = True
                            break
                        if event['type']=='event' and event['data'].get('ws_type')=='session_end':
                            raise RuntimeError('CLI exited before a result')
                        if event['type']=='event' and event['data'].get('ws_type')=='stderr' and 'Authentication required' in str(event['data'].get('data', '')):
                            raise RuntimeError('CLI authentication unavailable in this environment; sign in with agy in a terminal')
                assert saw_result
            finally:
                await client.post('/api/session/stop')
        history = await client.get('/api/approvals')
        history.raise_for_status()
        verification = (await client.get('/api/audit/verify')).json()
        assert verification['verified'], verification
        print('REST, WebSocket, session, approval history and audit checks passed:', verification['total'], 'events')


if __name__ == '__main__':
    asyncio.run(main())
