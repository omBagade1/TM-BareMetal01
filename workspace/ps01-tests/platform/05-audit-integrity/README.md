# Audit Integrity

Record tool calls, decisions, reasons and their audit IDs. Use GET /api/audit/verify without mutating the live log. Run python -m unittest discover -s backend -p test_agentguard.py from the project root for disposable integrity tests. Legacy chain coverage does not authenticate timestamps/event labels; document that limitation.

Status: NOT RUN. Record configuration, observations and evidence before assigning a result.
