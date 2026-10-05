# Installation design

## Product promise

The product goal is to install Feather Prep inside the existing Windows first, while keeping Windows intact. On first launch, Feather automatically scans the local computer and exposes the report to its AI through MCP. The AI identifies a tested Windows/firmware adapter before any boot or partition change is offered. The user sees the results and a single clearly identified install target. The current build workflow packages the first x64 per-user Windows launcher and scanner. The compiled installer and a trusted code-signing certificate are not included in this source ZIP. This is an initial modern Windows test target, not support for every Windows generation.

## Boot and disk lifecycle

Install Feather Prep in existing Windows -> first launch automatically scans hardware -> AI checks the report against tested compatibility adapters -> fetch verified boot files and OS payload -> prepare internal staging -> register Feather Setup boot -> restart into Feather Setup -> test hardware and network drivers -> offer the Windows replacement step -> establish Feather's permanent boot -> restart into Feather -> connect cloud AI.

Downloaded code does not become executable firmware by itself. Each Windows-generation adapter must establish a working boot path on that specific Windows, CPU-architecture, and firmware combination. The adapter must account for Windows boot manager differences, BIOS/UEFI, Secure Boot, disk and partition layout, and the networking and certificate support available to the downloader. The staging area and boot files must remain readable until the replacement system can boot independently. Windows partition replacement occurs from Feather Setup, after the first reboot.

The eventual installer must discover partition identities, not assume C: is disk 0 or that an EFI/system/recovery partition is disposable. Disk free space alone does not prove a partition can be shrunk: filesystem state and unmovable files matter. Network drivers must be tested under Feather; working networking under Windows is insufficient evidence.

## All-Windows compatibility plan

The intended coverage is all Windows generations users may still run, from legacy releases to current versions, rather than a product limited to XP or Windows 7. Build and test one adapter at a time, recording the exact Windows edition/build, x86/x64/ARM architecture, BIOS or UEFI mode, Secure Boot state, disk format, and network capabilities it supports. Some old systems will need a native launcher because they cannot run modern PowerShell or TLS clients; newer systems may require a different boot integration. A release must publish its tested compatibility matrix and report unsupported combinations before it changes the disk.

Start implementation on a known x86_64 laptop with one chosen Windows/firmware combination, then add further combinations based on test results. This sequence is a development plan, not a limit on the product goal and not a claim that the current checker or installer has been validated on any such machine. Legacy hardware may be 32-bit only, and old Windows download clients can have modern HTTPS/certificate limitations.

Inventory one real machine, implement that adapter, and demonstrate the entire no-removable-media conversion in an appropriate VM before installing on a laptop. Firmware, partition and hardware identifiers missing from the initial inventory require additional probes.

## Cloud AI and local agent

FeatherOS is the AI-controlled operating environment. A local Feather agent connects the AI model to the computer's OS and hardware; MCP is the standard tool interface that lets compatible AI clients use those exposed capabilities. The same control design should work across Feather-supported machines, and Windows compatibility adapters let people launch Feather Prep from different Windows generations before installation. MCP alone does not supply a model or grant a machine's capabilities: the model, local agent, permissions, drivers, and OS services must all be present. The AI model may run in a cloud service. Offline operation still needs the deterministic OS, desktop and remote-desktop client. A model outage must not prevent basic local boot.

AI changes to the Feather codebase become commits and built packages/images. Installing a new release is a distinct operation from editing source; keep an earlier bootable release for recovery. Proprietary firmware and drivers may not offer editable source. Rewriting BIOS is outside the OS installation route.

## Sources

- Debian hard-disk installer boot: https://www.debian.org/releases/bookworm/amd64/apas02.en.html
- Debian hard-disk boot preparation: https://d-i.debian.org/doc/installation-guide/nn.amd64/ch04s04.html
- Microsoft volume shrink limits (current documentation, not proof of XP support): https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shrink
