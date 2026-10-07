# FeatherOS Starter — Feather AI Core 0.6

First working layer: the computer's AI centre. FeatherOS is intended to run across a broad range of PCs, with a cloud-connected AI agent controlling Feather through a local system service and exposing machine tools over MCP. Run a small local agent, connect a cloud model or MCP client, inspect the machine, edit Feather's source and user projects, run commands, keep code revisions on disk, and interact by typing or voice.

MCP is the tool-connection protocol, not the operating system itself. Feather's local agent connects the AI to the OS and hardware; the AI can use the tools the agent exposes. The long-term goal is for this AI control layer to work across Feather computers and supported Windows installations, with a matching compatibility adapter for each Windows generation and machine setup.

## What works in this starter

- Windows launcher with an automatic hardware scan, bounded report to the private Vercel registry, and a simple local scan-details page.
- Online AI worker for a configured HTTPS chat-completions-compatible model with function calling; when online and local providers are both configured, online is selected by default.
- Optional local adapter for an OpenAI-compatible server on the same computer, with a cautious RAM/CPU/graphics resource profile and Feather AI chat page.
- MCP stdio tools for computer information, file edits, current-user commands, revisions and dashboard tasks.
- Automatic read-only hardware scan as soon as the local Feather agent starts on supported Windows and Linux hosts; the AI can read the results through MCP.
- Scan-details page that displays the read-only scan results and lets the user download local JSON for review.
- Persistent user work, tasks, activity and revisions on the hard drive.
- A download/verification staging script for an existing separate Windows volume, plus a Debian live preview build recipe.

## Start Feather AI Core

The development source can run on Python 3.9 or newer on Linux or supported modern Windows; it needs no pip dependencies. Windows users should use the self-contained Windows bundle built by `.github/workflows/build-windows.yml`, which does not require Python to be installed.

Windows release: download the versioned installer (for example, `FeatherOS-Setup-0.6.11.exe`) from the [FeatherOS releases](https://github.com/andykamseng-jpg/featheros/releases), then run it on your Windows PC. Setup installs Feather Prep for the current user and launches it automatically when installation finishes and performs a read-only hardware scan; it does not wipe Windows or install a replacement OS. This early test build is unsigned and may be blocked or warned about by Windows security controls; do not disable protections to run it. The ZIP in this project contains source code, not the compiled installer. Read `build/windows/README.md` for build steps, signing, and support limits.

Linux: run `sh START-AGENT.sh`.

The Windows launcher does not open a browser automatically. Select **Open Feather AI** to open the local chat and hardware report. The desktop window shows whether the registry accepted the report.

Open **Feather AI** from the desktop app to chat and submit tasks. Use **Set up online AI** for an HTTPS provider or **Set up local AI** for an OpenAI-compatible endpoint on this PC. Online AI is preferred when both are configured; local can be explicitly selected, and is used automatically when it is the only configured provider. Local setup saves only the endpoint and model name. Online provider secrets stay in memory for that run and are not saved. The local endpoint must be loopback (`localhost`, `127.0.0.1`, or `::1`).

Feather AI keeps a bounded history of up to eight completed user/assistant turns per conversation on this PC and sends it with later turns in that conversation. Start a new conversation to clear its active history. Do not enter secrets or sensitive information you do not want stored in the local task history. This does not include browser automation, bundled or downloaded model weights, or a replacement for Windows; Feather Prep still runs inside Windows.

To let the AI execute commands as your user account, start with `python3 -m agent.server --enable-commands`.

Commands run with that account's authority; file-tool roots do not restrict commands. Start the agent once: an MCP client launching it also serves the dashboard, so stop a standalone instance before launching that client, or select another --port and data directory.

Once Feather is running on a computer, its AI can call `system_info` to collect OS, processor, memory, firmware, disk, graphics, network and installed-driver details locally. This inventory does not change the computer. The current Windows probe requires a supported Python runtime and PowerShell; Feather Prep still needs a trusted, tested launcher before it can start on every Windows generation.

The `system_info` result also includes a cautious AI resource profile based on RAM, logical processor count and graphics names. It is only a planning hint; it does not guarantee a model will fit or run well. Benchmark local models on each target computer before choosing a model. No model weights are bundled or downloaded. See `design/LOCAL-AI-CORE.md` for this stage's limits.

See design/MCP-CONNECTION.md for MCP configuration and the optional cloud worker. No account, hosted model, provider credential, subscription or perpetual cloud session is included. Connection checks and real provider calls need your configured service. An old laptop can use cloud inference without a local model/GPU, but its installed Feather runtime still needs drivers for the actual hardware.

## Automatic hardware scan

Feather's intended sequence is: install the Feather Prep app into the existing Windows installation -> start Feather for the first time -> Feather scans the local computer automatically -> the connected AI reads the report -> Feather identifies a compatible setup path. This scan does not repartition the disk, change boot settings, or erase Windows.

A push to main that passes the Windows tests and build automatically creates the next patch release. Feather Prep checks official GitHub releases once when it starts. Earlier builds also registered a 30-minute Windows task; version 0.6.10 removes that legacy task during installation to prevent duplicate update attempts. It stages a newer installer only after checking its release digest, then updates through Inno Setup. Builds 0.6.5 and earlier require a manual installer if their older updater cannot run. Version 0.6.8 changes the Windows package from one-file extraction to a one-folder runtime to address a python312.dll load error from the temporary extraction folder. If an earlier installation shows that error and cannot open, download and run the 0.6.8 installer once; later upgrades can use the normal updater. A server cannot wake or install into a PC that is offline or has not checked for updates. Windows security controls may still block unsigned installers. The Windows launcher now sends a bounded hardware report to the private Vercel registry by default after scanning; the checkbox can stop future reports and unregister this PC. The check-in endpoint is publicly reachable, while the PC roster API remains protected by its admin key. The current agent implements automatic read-only inventory for Windows and Linux. Its Windows probe uses PowerShell/WMI and includes OS, processor, memory, firmware, disk, graphics, network and a bounded list of drivers. It has only been tested with simulated PowerShell output, not on your laptop; older Windows versions need compatible native launchers and their own boot adapters.

The goal is to let people start Feather Prep from any Windows generation they still use, from legacy releases through current Windows. The current ZIP does not yet provide this: the Python/browser core requires a supported modern runtime, and there is no tested universal launcher. Feather Prep needs separate, tested adapters for Windows version/build, CPU architecture, firmware boot mode, disk layout, and available network/TLS support.

## Installation roadmap

The intended final product installs Feather Prep inside the existing Windows first, then automatically scans before making any disk or boot changes. After the AI identifies a tested compatible route and the user chooses to continue, Feather stages Setup on the internal drive, reboots into Setup, checks hardware/network support, and only then offers the Windows replacement step. The product goal covers supported Windows generations and uses no USB.

This ZIP is not a finished OS installer and does not erase Windows. The all-Windows compatibility matrix, per-generation launchers and boot adapters, disk repartitioning, the actual replacement/wiper, signed bootable release and automatic OS upgrades are not implemented. windows/PREPARE-STAGING.ps1 only downloads hash-verified files from a real supplied release manifest onto an already existing separate volume; it cannot install the example manifest. build/BUILD-LIVE-PREVIEW.sh is an unexecuted recipe for a Linux live preview, not the no-USB installer.

Feather's AI can edit source, save revisions and verify changes when tools permit. Source edits need build/restart/deployment before they become running system changes. Code revisions are not disk snapshots. A local agent and cloud model supply the AI; this ChatGPT conversation is not embedded into firmware or moved onto the laptop.

## Voice

Microphone support depends on a current browser implementing SpeechRecognition and may use the browser's online transcription service. The UI displays typing when unsupported. Speaker output uses the browser's speech synthesis. Real audio devices and old-browser compatibility remain untested.

## Development verification

Run `python3 -m unittest discover -s tests -v`.

Tests cover the agent, MCP messages, local HTTP access, revisions, task persistence, a simulated cloud tool loop and installation-sequence invariants. Windows scripts, a real provider, physical audio, the live build and an OS replacement require separate testing.

