import unittest
from sequence import Conversion, Stage


class SequenceTests(unittest.TestCase):
    def staged(self):
        c = Conversion()
        c.mark_staged(partition="stage", payload_verified=True, boot_entry_verified=True)
        return c

    def setup(self):
        c = self.staged()
        c.mark_setup_booted(linux_drivers_tested=True, network_tested=True)
        return c

    def test_cannot_replace_windows_while_running_it(self):
        with self.assertRaises(ValueError):
            Conversion().mark_installed(target_partition="windows", target_confirmed=True,
                                        bootloader_verified=True)

    def test_payload_must_be_verified(self):
        with self.assertRaises(ValueError):
            Conversion().mark_staged(partition="stage", payload_verified=False,
                                     boot_entry_verified=True)

    def test_linux_network_must_work(self):
        with self.assertRaises(ValueError):
            self.staged().mark_setup_booted(linux_drivers_tested=True, network_tested=False)

    def test_staging_partition_is_preserved(self):
        with self.assertRaises(ValueError):
            self.setup().mark_installed(target_partition="stage", target_confirmed=True,
                                       bootloader_verified=True)

    def test_normal_sequence(self):
        c = self.setup()
        c.mark_installed(target_partition="windows", target_confirmed=True,
                         bootloader_verified=True)
        c.mark_active(installed_os_booted=True)
        self.assertEqual(c.stage, Stage.ACTIVE)


if __name__ == "__main__":
    unittest.main()
