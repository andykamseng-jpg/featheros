"""Feather installation sequence model. Does not perform OS/disk operations."""
from dataclasses import dataclass
from enum import Enum


class Stage(Enum):
    WINDOWS = "running_windows"
    STAGED = "feather_staged_on_internal_disk"
    SETUP = "running_feather_setup"
    INSTALLED = "feather_installed"
    ACTIVE = "running_feather"


@dataclass
class Conversion:
    stage: Stage = Stage.WINDOWS
    staging_partition: str = ""

    def mark_staged(self, *, partition: str, payload_verified: bool,
                    boot_entry_verified: bool):
        if self.stage != Stage.WINDOWS:
            raise ValueError("Staging requires the initial Windows phase")
        if not partition or not payload_verified or not boot_entry_verified:
            raise ValueError("Verified payload and an internal boot path are required")
        self.staging_partition = partition
        self.stage = Stage.STAGED

    def mark_setup_booted(self, *, linux_drivers_tested: bool, network_tested: bool):
        if self.stage != Stage.STAGED:
            raise ValueError("Setup must boot from a prepared internal staging area")
        if not linux_drivers_tested or not network_tested:
            raise ValueError("Feather hardware and networking must be tested")
        self.stage = Stage.SETUP

    def mark_installed(self, *, target_partition: str, target_confirmed: bool,
                       bootloader_verified: bool):
        if self.stage != Stage.SETUP:
            raise ValueError("Windows replacement is permitted only from Feather Setup")
        if not target_partition or target_partition == self.staging_partition:
            raise ValueError("Install target must preserve the staging partition")
        if not target_confirmed or not bootloader_verified:
            raise ValueError("Confirmed target and a verified permanent bootloader required")
        self.stage = Stage.INSTALLED

    def mark_active(self, *, installed_os_booted: bool):
        if self.stage != Stage.INSTALLED or not installed_os_booted:
            raise ValueError("Feather must boot successfully before activating its agent")
        self.stage = Stage.ACTIVE
