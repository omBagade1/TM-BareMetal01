import json
import os
import sys
import urllib.request


def denial_reason(reason):
    return (
        f"Blocked by AgentGuard. Reason: {reason.strip() or 'Permission was not granted.'} "
        "Tell the user clearly that AgentGuard blocked this action and explain the reason. "
        "Do not claim it succeeded or bypass a denied path, credential, human decision, or safety boundary. "
        "If the only issue is unsupported syntax for an otherwise permitted task, continue with a supported "
        "equivalent under AgentGuard's normal policy checks; do not ask the user to repeat the task."
    )


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"decision": "deny", "reason": denial_reason("Empty hook input (fail closed).")}))
        return
    try:
        payload = json.loads(raw)
        base = payload.get("toolCall") or payload
        tool = base.get("name") or ""
        args = base.get("args") or {}
    except Exception:
        print(json.dumps({"decision": "deny", "reason": denial_reason("Unparsable hook input (fail closed).")}))
        return

    backend = os.environ.get("AGENTGUARD_URL", "http://127.0.0.1:8911")
    secret = os.environ.get("AGENTGUARD_SECRET", "")
    terminal_id = os.environ.get("AGENTGUARD_TERMINAL_ID")
    request_body = {"secret": secret, "toolCall": {"name": tool, "args": args}}
    if terminal_id:
        request_body["terminal_id"] = terminal_id
    body = json.dumps(request_body).encode("utf-8")
    req = urllib.request.Request(
        backend.rstrip("/") + "/internal/hook/evaluate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("AGENTGUARD_HOOK_HTTP_TIMEOUT", "300"))) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        # agy's protobuf hook parser rejects unknown fields, including the
        # backend's rule_id. Keep audit metadata on the backend side.
        # Never accept delegated native review: force_ask did not prompt in a
        # live interactive agy 1.3.3 session. Also deny responses from an old
        # backend still running the removed delegation code until restart.
        if not isinstance(out, dict) or out.get("decision") not in ("allow", "block"):
            raise ValueError("Invalid backend decision")
        if not isinstance(out.get("reason"), str):
            raise ValueError("Invalid backend reason")
        out = {"decision": "deny" if out["decision"] == "block" else out["decision"], "reason": out["reason"]}
        if out["decision"] == "deny":
            out["reason"] = denial_reason(out["reason"])
        if out["decision"] == "allow" and tool == "run_command":
            command = args.get("CommandLine")
            # The grant is scoped to this hook invocation and the complete
            # approved command, never a global/persistent command wildcard.
            if isinstance(command, str) and command.strip() and command.strip() != "*" and not command.startswith("regex:"):
                out["permissionOverrides"] = [f"command({command})"]
    except Exception:
        out = {
            "decision": "deny",
            "reason": denial_reason("Backend unreachable or invalid response; failing closed."),
        }
    print(json.dumps(out))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
