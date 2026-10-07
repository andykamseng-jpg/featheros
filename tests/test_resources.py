import unittest
from agent.resources import resource_profile
from agent.registry import hardware_summary


class ResourceTests(unittest.TestCase):
    def test_windows_resource_facts_reach_registry_without_identifiers(self):
        hardware = {
            'computer': [{'TotalPhysicalMemory': '17179869184', 'SerialNumber': 'private'}],
            'operating_system': [{'FreePhysicalMemory': '8388608'}],
            'processors': [{'Name': 'Test CPU', 'NumberOfCores': 8, 'NumberOfLogicalProcessors': 16, 'ProcessorId': 'private'}],
            'graphics': [{'Name': 'Integrated GPU', 'AdapterRAM': 1073741824}],
            'disks': [{'Model': 'SSD', 'Size': '512000000000', 'SerialNumber': 'private'}],
        }
        result = hardware_summary(hardware)['resources']
        self.assertEqual(result['memoryTotalBytes'], 16 * 1024**3)
        self.assertEqual(result['memoryAvailableBytes'], 8 * 1024**3)
        self.assertEqual(result['processors'][0]['cores'], 8)
        self.assertEqual(result['storage'][0]['sizeBytes'], 512000000000)
        self.assertNotIn('private', str(result))
        self.assertEqual(result['modelFit'], 'benchmark_required')

    def test_unknown_and_invalid_values_remain_unknown(self):
        result = resource_profile({'computer': [{'TotalPhysicalMemory': True}],
                                   'graphics': [{'AdapterRAM': -1}],
                                   'processors': [{'NumberOfCores': 99999}]})
        self.assertIsNone(result['memoryTotalBytes'])
        self.assertIsNone(result['memoryAvailableBytes'])
        self.assertIsNone(result['graphics'][0]['reportedAdapterBytes'])
        self.assertIsNone(result['processors'][0]['cores'])

    def test_linux_memory_and_bounded_lists(self):
        result = resource_profile({'memory_total_kib': 1024, 'processor': 'Linux CPU',
                                   'disks': [{'model': 'SSD', 'size_bytes': 1000}] * 100})
        self.assertEqual(result['memoryTotalBytes'], 1024**2)
        self.assertEqual(result['processors'][0]['name'], 'Linux CPU')
        self.assertEqual(len(result['storage']), 16)
