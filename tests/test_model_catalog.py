import unittest

from agent.model_catalog import GIB, candidates


class ModelCatalogTests(unittest.TestCase):
    def test_missing_readings_never_claim_a_model_fits(self):
        self.assertTrue(all(item["readiness"] == "measure_memory" for item in candidates({})))

    def test_16_gib_machine_only_recommends_small_trials(self):
        models = {item["name"]: item for item in candidates({
            "memoryTotalBytes": 16 * GIB, "memoryAvailableBytes": 9 * GIB,
            "graphics": [{"name": "Intel Graphics", "reportedAdapterBytes": 8 * GIB}],
        })}
        self.assertEqual(models["deepseek-r1:7b"]["readiness"], "benchmark_required")
        self.assertEqual(models["deepseek-r1:14b"]["readiness"], "unlikely")
        self.assertEqual(models["qwen3-coder:30b"]["readiness"], "unlikely")

    def test_32_gib_machine_can_trial_14b_but_requires_more_free_ram_for_30b(self):
        models = {item["name"]: item for item in candidates({
            "memoryTotalBytes": 32 * GIB, "memoryAvailableBytes": 17 * GIB,
        })}
        self.assertEqual(models["deepseek-r1:14b"]["readiness"], "benchmark_required")
        self.assertEqual(models["qwen3-coder:30b"]["readiness"], "unlikely")

    def test_large_trial_still_requires_benchmark(self):
        models = {item["name"]: item for item in candidates({
            "memoryTotalBytes": 64 * GIB, "memoryAvailableBytes": 40 * GIB,
        })}
        self.assertEqual(models["deepseek-r1:32b"]["readiness"], "benchmark_required")

    def test_disk_space_is_checked_before_a_trial(self):
        models = {item["name"]: item for item in candidates({
            "memoryTotalBytes": 64 * GIB, "memoryAvailableBytes": 40 * GIB,
        }, disk_free_bytes=6 * 1000 ** 3)}
        self.assertEqual(models["qwen2.5-coder:7b"]["readiness"], "insufficient_disk")


if __name__ == "__main__":
    unittest.main()
