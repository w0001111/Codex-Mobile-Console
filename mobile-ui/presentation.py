# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Visible messages only: no hidden reasoning, raw tool arguments or generic file access."""
import hashlib
import re

def clean(text,limit):
    return re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+", "[已隐藏凭据]", str(text))

TOOL_NAMES={'commandExecution':'执行命令','fileChange':'修改文件','mcpToolCall':'调用工具','webSearch':'检索资料','imageGeneration':'生成图片','collabAgentToolCall':'协作任务'}

def turn_id(turn):return turn.get('turnId') or turn.get('id') or ''
def timestamp(turn):return turn.get('turnStartedAtMs') or (turn.get('startedAt') or 0)*1000

def normalize_turn(turn):
    from model_settings import turn_settings
    tid=turn_id(turn);items=[]
    for i,item in enumerate(turn.get('items',[])):
        kind=item.get('type');text='';role=''
        if kind=='userMessage':
            role='user';parts=[]
            for c in item.get('content',[]):
                if c.get('type') in ('text','inputText'):parts.append(c.get('text',''))
                elif c.get('type') in ('image','localImage','inputImage'):parts.append('〔图片附件：请在桌面查看〕')
                else:parts.append('〔附件：请在桌面查看〕')
            text='\n'.join(parts)
        elif kind=='agentMessage':role='result' if item.get('phase')=='final_answer' else 'feedback';text=item.get('text','')
        elif kind in TOOL_NAMES:
            role='operation';state=item.get('status','');text=TOOL_NAMES[kind]+(' · '+{'completed':'已完成','inProgress':'进行中','failed':'失败','declined':'未批准'}.get(state,'已记录'))
        if not role or not text:continue
        items.append({'id':item.get('id') or tid+':'+str(i),'role':role,'text':clean(text,len(text)+1)})
    return {'id':tid,'at':timestamp(turn),'status':turn.get('status','unknown'),'items':items,'executionSettings':turn_settings(turn)}

def final_revision(turn_list):
    for turn in reversed(turn_list):
        if turn.get('status')!='completed':continue
        finals=[x.get('text','') for x in turn.get('items',[]) if x.get('type')=='agentMessage' and x.get('phase')=='final_answer']
        if finals:return hashlib.sha256((turn_id(turn)+'\0'+'\n'.join(finals)).encode()).hexdigest()
    return ''
