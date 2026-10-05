import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from agent.core import Agent, WINDOWS_INVENTORY_SCRIPT, windows_hardware_inventory
from agent.server import rpc, make_http
from agent.cloud import run_task


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.agent = Agent(self.root / 'data', self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_ai_can_create_and_edit_files(self):
        self.agent.call('file_write', {'path':'app/main.py','content':'print(1)'})
        self.assertEqual(self.agent.call('file_read', {'path':'app/main.py'})['content'], 'print(1)')
        self.agent.call('file_write', {'root':'source','path':'theme.css','content':'body{}'})
        self.assertEqual((self.source / 'theme.css').read_text(), 'body{}')

    def test_paths_and_symlinks_cannot_escape(self):
        with self.assertRaises(ValueError):
            self.agent.call('file_write', {'path':'../escape','content':'x'})
        (self.agent.workspace / 'link').symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.agent.call('file_write', {'path':'link/escape','content':'x'})

    def test_revision_preserves_bytes(self):
        p = self.agent.workspace / 'binary.dat'
        p.write_bytes(b'\x00\xff\x01')
        revision = self.agent.call('revision_save', {'label':'before'})
        p.write_bytes(b'changed')
        self.agent.call('revision_restore', {'revision':revision['id']})
        self.assertEqual(p.read_bytes(), b'\x00\xff\x01')

    def test_command_permission(self):
        args = {'argv':[sys.executable,'-c',"print('Feather command')"]}
        with self.assertRaises(ValueError): self.agent.call('command_run', args)
        self.agent.enable_commands = True
        result = self.agent.call('command_run', args)
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('Feather command', result['output'])

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            self.agent.call('file_write', {'path':'a','content':3})
        with self.assertRaises(ValueError):
            self.agent.call('system_info', {'unexpected':True})

    def test_system_info_automatically_collects_local_platform_inventory(self):
        report = {'collection_mode':'read_only','firmware_mode':'UEFI','disks':[]}
        with patch('agent.core.platform.system', return_value='Windows'), \
             patch('agent.core.windows_hardware_inventory', return_value=report) as scan:
            agent = Agent(self.root / 'win-data', self.source)
            self.assertTrue(agent.hardware_ready.wait(1))
            result = agent.call('system_info', {})
        self.assertEqual(result['hardware'], report)
        scan.assert_called_once_with()

    def test_hardware_scan_starts_automatically_with_agent(self):
        report = {'collection_mode':'read_only','processor':'Test CPU'}
        with patch('agent.core.platform.system', return_value='Linux'), \
             patch('agent.core.linux_hardware_inventory', return_value=report) as scan:
            agent = Agent(self.root / 'auto-data', self.source)
            self.assertTrue(agent.hardware_ready.wait(1))
            self.assertEqual(agent.hardware_inventory, report)
        scan.assert_called_once_with()

    def test_windows_inventory_uses_fixed_read_only_wmi_query(self):
        payload = {'collection_mode':'read_only','firmware_mode':'UEFI','disks':[]}
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), '')
        with patch('agent.core.subprocess.run', return_value=completed) as run:
            result = windows_hardware_inventory()
        argv = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertEqual(result, payload)
        self.assertEqual(argv[0], 'powershell.exe')
        self.assertIn('Win32_BaseBoard', argv[-1])
        self.assertIn('Win32_DiskDrive', argv[-1])
        self.assertIn("collection_mode = 'read_only'", WINDOWS_INVENTORY_SCRIPT)
        self.assertNotIn('Remove-Item', WINDOWS_INVENTORY_SCRIPT)
        self.assertFalse(options.get('shell', False))
        self.assertEqual(options['timeout'], 25)

    def test_interruption_is_not_blindly_retried(self):
        task = self.agent.submit('build a calculator')
        self.assertEqual(self.agent.call('task_next', {})['id'], task['id'])
        again = Agent(self.agent.data, self.source)
        self.assertEqual(again.tasks[0]['state'], 'interrupted')
        self.assertEqual(again.call('task_next', {}), {'task':None})

    def test_reply_finishes_task(self):
        t = self.agent.submit('hello')
        self.agent.call('task_next', {})
        self.agent.call('task_reply', {'id':t['id'],'text':'hello back'})
        self.assertEqual(self.agent.tasks[0]['reply'], 'hello back')

    def test_mcp_handshake_and_modern_probe(self):
        result = rpc(self.agent, {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}})
        self.assertEqual(result['result']['protocolVersion'], '2025-06-18')
        self.assertIn('tools', rpc(self.agent, {'jsonrpc':'2.0','id':2,'method':'tools/list'})['result'])
        self.assertEqual(rpc(self.agent, {'jsonrpc':'2.0','id':3,'method':'server/discover'})['error']['code'], -32601)
        self.assertIsNone(rpc(self.agent, {'jsonrpc':'2.0','method':'notifications/initialized'}))

    def test_cloud_tool_loop_simulated_provider(self):
        class Response:
            def __init__(self, message): self.data = json.dumps({'choices':[{'message':message}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, *args): return self.data
        replies = [Response({'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'file_write','arguments':json.dumps({'path':'cloud.txt','content':'cloud-created'})}}]}), Response({'role':'assistant','content':'Created cloud.txt'})]
        with patch.dict(os.environ, {'FEATHER_AI_URL':'https://example.invalid/chat/completions','FEATHER_AI_KEY':'test-only','FEATHER_AI_MODEL':'mock'}), patch('agent.cloud.urllib.request.urlopen', side_effect=replies) as mock:
            self.assertEqual(run_task(self.agent, 'write a file'), 'Created cloud.txt')
            self.assertEqual(mock.call_count, 2)
        self.assertEqual((self.agent.workspace / 'cloud.txt').read_text(), 'cloud-created')

    def test_http_access_controls_and_queue(self):
        server = make_http(self.agent, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        try:
            page = urllib.request.urlopen(url).read().decode()
            token = page.split("const token='")[1].split("'")[0]
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url + '/api/state')
            self.assertEqual(error.exception.code, 403)
            req = urllib.request.Request(url + '/api/task', data=b'{"text":"test desktop"}', headers={'X-Feather-Token':token,'Content-Type':'application/json'})
            self.assertEqual(json.loads(urllib.request.urlopen(req).read())['state'], 'queued')
            bad = urllib.request.Request(url + '/api/task', data=b'{"text":"bad"}', headers={'X-Feather-Token':token,'Origin':'https://external.invalid'})
            with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(bad)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_actual_stdio_process(self):
        requests = [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'file_write','arguments':{'path':'stdio.txt','content':'real subprocess'}}}]
        env = dict(os.environ)
        for name in ('FEATHER_AI_URL','FEATHER_AI_KEY','FEATHER_AI_MODEL'): env.pop(name, None)
        result = subprocess.run([sys.executable,'-m','agent.server','--mcp','--port','0','--data-dir',str(self.root / 'stdio')], input='\n'.join(json.dumps(r) for r in requests)+'\n', capture_output=True, text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([json.loads(line)['id'] for line in result.stdout.splitlines()], [1,2,3])
        self.assertEqual((self.root / 'stdio/workspace/stdio.txt').read_text(), 'real subprocess')


if __name__ == '__main__': unittest.main()
