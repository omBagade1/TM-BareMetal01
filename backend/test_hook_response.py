"""CLI wire-format regression: backend metadata must not reach hook stdout."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from hook.agentguard_hook import main, denial_reason


class HookResponseTests(unittest.TestCase):
    def invoke(self, response, call=None):
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(call or {'name':'list_dir','args':{}}))), \
                patch("urllib.request.urlopen") as request, \
                contextlib.redirect_stdout(output):
            request.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            main()
        return json.loads(output.getvalue())

    def test_only_cli_fields_emitted_for_allow_and_block(self):
        for decision in ("allow", "block"):
            with self.subTest(decision=decision):
                self.assertEqual(
                    self.invoke({"decision": decision, "reason": "Policy decision",
                                 "rule_id": "__default", "extra": {"internal": True}}),
                    {"decision": "deny" if decision == "block" else "allow", "reason": denial_reason("Policy decision") if decision == "block" else "Policy decision"},
                )

    def test_denial_names_guard_and_explains_cause_to_agent(self):
        result = self.invoke({'decision': 'block', 'reason': 'Path is outside the approved workspace.'})
        self.assertIn('Blocked by AgentGuard.', result['reason'])
        self.assertIn('Reason: Path is outside the approved workspace.', result['reason'])
        self.assertIn('Tell the user clearly', result['reason'])
        self.assertIn('Do not claim it succeeded or bypass', result['reason'])
        self.assertIn('only issue is unsupported syntax', result['reason'])

    def test_command_grant_only_after_backend_approval(self):
        command = 'Get-ChildItem | Select-Object Name, Length, Mode, LastWriteTime'
        call = {'name':'run_command', 'args':{'CommandLine':command}}
        allowed = self.invoke({'decision':'allow', 'reason':'Approved'}, call)
        self.assertEqual(allowed, {'decision':'allow', 'reason':'Approved',
                                  'permissionOverrides':[f'command({command})']})
        denied = self.invoke({'decision':'block', 'reason':'Blocked',
                              'permissionOverrides':['command(*)']}, call)
        self.assertEqual(denied, {'decision':'deny', 'reason':denial_reason('Blocked')})
        for command in ('*', 'regex:.*', '', None):
            call['args']['CommandLine'] = command
            result = self.invoke({'decision':'allow', 'reason':'Approved'}, call)
            self.assertNotIn('permissionOverrides', result)

    def test_invalid_backend_responses_fail_closed(self):
        for response in (None, [], {}, {"decision": "ask", "reason": "pending"},
                         {"decision": "allow"}, {"decision": "allow", "reason": 42}):
            with self.subTest(response=response):
                result = self.invoke(response)
                self.assertEqual(result["decision"], "deny")
                self.assertEqual(set(result), {"decision", "reason"})

    def test_native_review_delegation_fails_closed(self):
        response = {'decision': 'force_ask', 'reason': 'Review in CLI',
                    'permissionOverrides': ['command(*)'], 'rule_id': 'internal'}
        call = {'name': 'run_command', 'args': {'CommandLine': 'Get-ChildItem'}}
        with patch.dict('os.environ', {'AGENTGUARD_TERMINAL_ID': 'test-terminal'}):
            self.assertEqual(self.invoke(response, call)['decision'], 'deny')
            self.assertEqual(self.invoke(response, {'name': 'view_file', 'args': {}})['decision'], 'deny')
        with patch.dict('os.environ', {'AGENTGUARD_TERMINAL_ID': ''}):
            self.assertEqual(self.invoke(response, call)['decision'], 'deny')


if __name__ == "__main__":
    unittest.main()
