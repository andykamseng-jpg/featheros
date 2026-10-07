import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request
from unittest.mock import patch

from agent import assistant, local_ai
from agent.core import Agent


class LocalAiTests(unittest.TestCase):
    def make_agent(self, data, source):
        report={'collection_mode':'read_only','status':'test'}
        with patch('agent.core.windows_hardware_inventory', return_value=report), \
             patch('agent.core.linux_hardware_inventory', return_value=report):
            agent=Agent(data, source)
            self.assertTrue(agent.hardware_ready.wait(3))
        return agent

    def test_loopback_only_and_valid_endpoint_shapes(self):
        for endpoint in (
            'http://127.0.0.1:11434/v1/chat/completions',
            'http://localhost:1234/v1/chat/completions',
            'http://[::1]:1234/v1/chat/completions',
        ):
            self.assertEqual(local_ai.validate_endpoint(endpoint), endpoint)
        for endpoint in (
            'https://example.com/v1/chat/completions',
            'http://192.168.1.2:1234/v1/chat/completions',
            'http://localhost/v1/chat/completions',
            'http://user:pass@127.0.0.1:1234/chat',
            'http://127.0.0.1:1234/v1/chat/completions?token=secret',
            'http://127.0.0.1:1234/v1/chat/completions#secret',
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                local_ai.validate_endpoint(endpoint)
        proxies=[handler for handler in local_ai._LOOPBACK_OPENER.handlers
                 if isinstance(handler, ProxyHandler)]
        self.assertTrue(all(handler.proxies == {} for handler in proxies))
        redirect=next(handler for handler in local_ai._LOOPBACK_OPENER.handlers
                      if isinstance(handler, local_ai._LoopbackRedirect))
        with self.assertRaises(ValueError):
            redirect.redirect_request(Request('http://127.0.0.1:11434/'), None,
                                      302, 'Found', {}, 'https://example.com/leak')

    def test_only_nonsecret_endpoint_and_model_are_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            local_ai.save_settings(temp, 'http://127.0.0.1:11434/v1/chat/completions', 'qwen3.5:2b')
            stored = json.loads(Path(temp, 'local-ai.json').read_text())
            self.assertEqual(stored, {'endpoint': 'http://127.0.0.1:11434/v1/chat/completions', 'model': 'qwen3.5:2b'})
            self.assertNotIn('key', stored)
            self.assertEqual(local_ai.load_settings(temp), stored)

    def test_local_is_default_even_if_online_is_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp, 'source'); source.mkdir()
            agent=self.make_agent(Path(temp, 'data'), source)
            with patch('agent.assistant.cloud.configured', return_value=True):
                self.assertEqual(assistant.selected_provider(agent), 'local')
                self.assertFalse(assistant.configured(agent))
                local_ai.save_settings(agent.data, 'http://127.0.0.1:11434/v1/chat/completions', 'local-model')
                self.assertTrue(assistant.configured(agent))
                assistant.select_provider(agent, 'online')
                self.assertTrue(assistant.configured(agent))

    def test_saved_hardware_profile_survives_restart_and_reaches_ai_context(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp, 'source'); source.mkdir()
            data=Path(temp, 'data'); data.mkdir()
            saved={'scanned_at':'2026-10-08T00:00:00+00:00','hardware':{
                'collection_mode':'read_only',
                'computer':[{'Manufacturer':'Dell Inc.','Model':'Feather test PC','TotalPhysicalMemory':16000000000}],
                'processors':[{'Name':'Feather test CPU','NumberOfCores':8,'NumberOfLogicalProcessors':16}],
                'operating_system':[{'Caption':'Windows 11','FreePhysicalMemory':4000000}],
                'graphics':[{'Name':'Integrated GPU','DriverVersion':'1.2','PNPDeviceID':'unique-device-path'}],
                'disks':[{'Model':'Local SSD','Size':512000000000}],
                'installed_drivers':[],
            }}
            Path(data, 'hardware-profile.json').write_text(json.dumps(saved))
            with patch('agent.core.platform.system', return_value='Linux'), \
                 patch('agent.core.linux_hardware_inventory', return_value={'collection_mode':'read_only','status':'unavailable'}):
                agent=Agent(data, source)
                self.assertTrue(agent.hardware_ready.wait(3))
            self.assertEqual(agent.call('system_info', {})['hardware']['computer'][0]['Model'], 'Feather test PC')
            self.assertEqual(agent.call('system_info', {})['hardware_profile_saved_at'], saved['scanned_at'])
            context=agent.hardware_context()
            self.assertEqual(context['processors'][0]['name'], 'Feather test CPU')
            self.assertEqual(context['graphics'][0]['name'], 'Integrated GPU')
            self.assertNotIn('unique-device-path', json.dumps(context))

    def test_successful_scan_is_saved_and_failed_scan_keeps_last_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp, 'source'); source.mkdir()
            data=Path(temp, 'data')
            report={'collection_mode':'read_only','computer':[{'Model':'Fresh scan PC'}]}
            with patch('agent.core.platform.system', return_value='Windows'), \
                 patch('agent.core.windows_hardware_inventory', return_value=report):
                agent=Agent(data, source)
                self.assertTrue(agent.hardware_ready.wait(3))
            saved=json.loads(Path(data, 'hardware-profile.json').read_text())
            self.assertEqual(saved['hardware']['computer'][0]['Model'], 'Fresh scan PC')
            with patch('agent.core.platform.system', return_value='Windows'), \
                 patch('agent.core.windows_hardware_inventory', return_value={'collection_mode':'read_only','status':'unavailable'}):
                again=Agent(data, source)
                self.assertTrue(again.hardware_ready.wait(3))
            self.assertEqual(again.call('system_info', {})['hardware']['computer'][0]['Model'], 'Fresh scan PC')
            self.assertEqual(json.loads(Path(data, 'hardware-profile.json').read_text()), saved)

    def test_local_model_request_contains_saved_hardware_context(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp, 'source'); source.mkdir()
            agent=self.make_agent(Path(temp,'data'), source)
            agent.hardware_profile={'scanned_at':'today','hardware':{
                'processors':[{'Name':'Feather-context CPU'}],
                'graphics':[{'Name':'Local GPU','PNPDeviceID':'unique-instance-42'}]}}
            agent.hardware_inventory={'collection_mode':'read_only','status':'unavailable'}
            local_ai.save_settings(agent.data, 'http://127.0.0.1:11434/v1/chat/completions', 'test-model')
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, *args): return json.dumps({'choices':[{'message':{'content':'ready'}}]}).encode()
            with patch.object(local_ai._LOOPBACK_OPENER, 'open', return_value=Response()) as send:
                self.assertEqual(local_ai.run_task(agent, 'hello'), 'ready')
            payload=json.loads(send.call_args.args[0].data)
            self.assertIn('Feather-context CPU', payload['messages'][0]['content'])
            self.assertNotIn('unique-instance-42', payload['messages'][0]['content'])
            self.assertNotIn('system_info', [item['function']['name'] for item in payload['tools']])
            self.assertEqual(payload['model'], 'test-model')

    def test_local_model_can_make_a_file_tool_call(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp, 'source'); source.mkdir()
            agent=self.make_agent(Path(temp,'data'), source)
            local_ai.save_settings(agent.data, 'http://127.0.0.1:11434/v1/chat/completions', 'test-model')
            class Response:
                def __init__(self, message):
                    self.data=json.dumps({'choices':[{'message':message}]}).encode()
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, *args): return self.data
            replies=[Response({'role':'assistant','content':None,'tool_calls':[{
                'id':'call-1','type':'function','function':{'name':'file_write',
                'arguments':json.dumps({'path':'hello.txt','content':'local write'})}}]}),
                Response({'role':'assistant','content':'Wrote the file.'})]
            with patch.object(local_ai._LOOPBACK_OPENER, 'open', side_effect=replies) as send:
                self.assertEqual(local_ai.run_task(agent, 'write hello.txt'), 'Wrote the file.')
            self.assertEqual((agent.workspace/'hello.txt').read_text(), 'local write')
            self.assertEqual(send.call_count, 2)
