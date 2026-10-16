import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from app import main

class ActionIssueTests(unittest.IsolatedAsyncioTestCase):
    async def check_decision(self, decision, approval=None):
        record={'id':123,'event_type':'policy_eval','payload':{},'decision':decision}
        audit=Mock()
        audit.append.return_value=record
        policy=Mock()
        policy.evaluate.return_value=(decision,'Policy reason','test-rule')
        approvals=Mock()
        approvals.request=AsyncMock(return_value=approval)
        with patch.object(main,'audit',audit), patch.object(main,'policy',policy), \
             patch.object(main,'approvals',approvals), patch.object(main,'broadcast',new_callable=AsyncMock) as broadcast, \
             patch.object(main,'broadcast_status',new_callable=AsyncMock), patch.object(main.config,'load_secret',return_value='test'):
            result=await main.internal_hook_evaluate(main.HookEvaluate(secret='test',toolCall={'name':'view_file','args':{'AbsolutePath':'outside.txt'}}))
            issues=[c.args[0] for c in broadcast.call_args_list if c.args[0]['type']=='action_issue']
            self.assertEqual(len(issues),int(result['decision']=='block'))
            if issues:self.assertEqual(issues[0]['data']['id'],123)
        return audit

    async def test_policy_block_and_allow(self):
        await self.check_decision('block')
        await self.check_decision('allow')

    async def test_human_and_timeout_blocks(self):
        for source in ('human','timeout'):
            rec={'id':'approval','ts':'now','tool':'view_file','args':{},'reason':'Timed out' if source=='timeout' else 'Review','decision':'block','decided_by':source}
            audit=await self.check_decision('ask',rec)
            self.assertEqual(audit.append.call_args.args[0],'approval_decided')
            self.assertEqual(audit.append.call_args.args[1]['decided_by'],source)

    async def test_tool_error_has_audit_link(self):
        with patch.object(main,'audit') as audit, patch.object(main,'broadcast',new_callable=AsyncMock) as broadcast:
            audit.append.return_value={'id':456}
            await main.handle_event({'event':'step_update','payload':{'step_type':'tool','state':'ERROR','tool_name':'run_command','tool_info':{'error':{'message':'Hook parse failed'}}}})
            self.assertEqual(broadcast.call_args.args[0],{'type':'action_issue','data':{'id':456}})
