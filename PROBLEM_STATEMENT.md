# PS01 — Agent Sandbox Escape Gauntlet

## Description

AI agents can now run shell commands, read files, and make web requests. If an agent reads a
file or webpage containing hidden instructions (indirect prompt injection), it may obey them —
for example, by sending cloud credentials to an attacker. You cannot fully stop this inside the
model, so you will build a sandbox that limits the damage a hijacked agent can do while still
letting it complete normal tasks. Build an isolated container runtime restricted to a /workspace
folder, a network allowlist that blocks and logs unapproved domains, a policy gate that checks
each tool call and returns a decision (allow, block, or ask) with a reason, resource limits (CPU,
memory, process count, run time), a tamper-evident audit log where each entry hashes the
previous one, and a dashboard showing live tool calls, decisions, and reasons. Teams must
build their own lightweight agent (using an open-weight model with shell/file/HTTP tool access),
write 3–5 normal tasks it should complete, and script 5–8 attack scenarios (e.g., credential theft,
DNS exfiltration, writes outside /workspace) to demonstrate containment. Scoring is
self-demonstrated: the demo video and live judging round must show attacks being blocked and
normal tasks still completing, with the audit log and policy decisions visible throughout.

## Tools & Technologies

Python agent loop calling Ollama (Qwen3-8B/4B or Llama 3.1 8B, 4-bit, based on available
hardware); Docker for container isolation (read-only root, dropped capabilities, non-root user,
custom seccomp profile — gVisor optional); Docker cgroup flags and Python subprocess
timeouts for resource limits; Squid and dnsmasq for network/DNS allowlisting; Open Policy
Agent (Rego) as the policy engine, or a simpler Python rule-checker if time is tight; Meta Llama
Prompt Guard 2 for text scoring; SQLite with a SHA-256 hash chain for the audit log; FastAPI
with WebSockets and a React + TypeScript dashboard, or Streamlit if short on time.
