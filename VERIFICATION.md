# Verification — Feather AI Core 0.6

Executed on the Linux development host:
- 18 offline Python tests passed, including persistent source seeding, automatic hardware scanning at agent startup, a mocked Windows WMI/PowerShell probe, MCP messages, cloud-tool execution using a simulated provider, current-user commands, file-root boundaries, code revision recovery and installation-sequence rules.
- Browser JavaScript syntax passed Node checking.
- Shell launcher and live-preview build recipe passed shell syntax checks.

The two loopback integration tests could not run in this restricted host because it denies local socket binding. The Windows PowerShell probe was mocked; it has not run on an actual Windows computer. The workflow for a bundled x64 Windows app and per-user installer is present, but was not run here: this host is Linux, has no PyInstaller or Windows build runner attached, and no signing certificate. The current ZIP is source code, not a compiled installer.

Not executed: Windows VBScript/PowerShell on Windows, any per-generation Windows launcher or boot adapter, real cloud model connection, microphone/speaker hardware, Debian live-image build, all-Windows compatibility, no-USB partition/boot conversion, or disk erasure.

The ZIP contains source code and an all-Windows compatibility design goal. It contains no compiled executable, bootable Feather image, model weights, provider credentials, or disk wiping/replacement code. The Windows build workflow bundles Python into the runtime when run on a Windows build host. The current scan and launcher have not been tested on your laptop.
