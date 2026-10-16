import asyncio
import uuid

from . import config


class ApprovalManager:
    def __init__(self):
        self._pending = {}
        self._history = []

    def pending_list(self) -> list[dict]:
        return [
            {
                "id": aid,
                "ts": rec["ts"],
                "tool": rec["tool"],
                "args": rec["args"],
                "reason": rec["reason"],
                "decided": False,
            }
            for aid, rec in self._pending.items()
        ]

    def history(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._history[-limit:]))

    async def request(self, tool: str, args: dict, reason: str, on_pending=None) -> dict:
        aid = uuid.uuid4().hex[:12]
        fut = asyncio.get_event_loop().create_future()
        rec = {
            "id": aid,
            "ts": config.utcnow(),
            "tool": tool,
            "args": args,
            "reason": reason,
            "decision": None,
            "decided_by": None,
            "future": fut,
        }
        self._pending[aid] = rec

        result = {
            "id": aid,
            "ts": rec["ts"],
            "tool": tool,
            "args": args,
            "reason": reason,
            "decision": None,
        }
        try:
            if on_pending:
                await on_pending(result.copy())
            decision = await asyncio.wait_for(fut, timeout=config.APPROVAL_TIMEOUT)
            rec["decision"] = decision
            rec["decided_by"] = "human"
        except asyncio.TimeoutError:
            rec["decision"] = "block"
            rec["decided_by"] = "timeout"
            result["reason"] += " (approval timed out)"
        finally:
            self._pending.pop(aid, None)
            self._history.append({k: v for k, v in rec.items() if k != "future"})
            self._history = self._history[-200:]
        result["decision"] = rec["decision"]
        result["decided_by"] = rec["decided_by"]
        return result

    def decide(self, aid: str, decision: str) -> bool:
        rec = self._pending.get(aid)
        if not rec or rec["future"].done():
            return False
        if decision not in ("allow", "block"):
            return False
        rec["future"].set_result(decision)
        return True
