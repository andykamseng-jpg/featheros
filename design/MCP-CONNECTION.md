# Connecting an AI to Feather

The development agent uses standard-library Python 3.9+ and serves MCP over stdin/stdout. The self-contained Windows build bundles this runtime and does not require Python to be installed. MCP is Feather's common AI-to-computer tool interface: the local Feather agent exposes operating system and hardware capabilities to a connected AI client. Windows compatibility belongs to the launch, hardware, and boot adapters around the agent, not to MCP itself.

The product goal is for this AI control design to cover FeatherOS computers and all Windows generations Feather Prep eventually supports. The current Windows build targets x64 modern Windows first; it is not a claim of tested support across every Windows release. Legacy Windows versions need their own compatible startup path, and each supported configuration needs real hardware testing.

Start from the extracted project directory:

```sh
python3 -m agent.server --mcp --data-dir /absolute/path/feather-data
```

For an MCP client supporting stdio configuration:

```json
{
  "mcpServers": {
    "feather": {
      "command": "python3",
      "args": ["-m", "agent.server", "--mcp", "--data-dir", "/absolute/path/feather-data"],
      "cwd": "/absolute/path/featheros-starter"
    }
  }
}
```

Client configuration schemas vary. Use its executable/path format; the supported starter protocol uses the MCP initialize lifecycle through 2025-11-25. Newer clients need legacy negotiation. A modern server/discover probe receives method-not-found to permit negotiation, rather than being left unanswered.

Available tools: system_info, file_list, file_read, file_write, revision_save, revision_list, revision_restore, command_run, task_next, task_reply. The agent begins a read-only hardware scan automatically when it launches on a supported Windows or Linux system, and `system_info` returns the result to the AI. The user does not need to type the model, CPU, memory, firmware, disk, graphics, or network details. The tools work only after the local agent is installed and running; future Feather adapters will add and validate capabilities for other platforms.

The source root is the extracted Feather project; the workspace root is under the chosen data directory. With `--enable-commands`, command_run executes with the current account's full privileges, beyond the file-tool roots. Commands have a 30-second timeout; commands may launch descendants requiring separate cleanup. This is not an operating-system sandbox.

Ask the connected AI: "Check task_next for dashboard requests, handle the returned task with Feather's tools, and finish with task_reply." An MCP server exposes tools; it does not by itself create a continuously thinking model or force a client to poll.

## Optional built-in cloud worker

Set these on the machine running Feather, then start the agent without --mcp:

- FEATHER_AI_URL: the complete HTTPS chat-completions endpoint of your provider.
- FEATHER_AI_MODEL: a model that supports function/tool calling.
- FEATHER_AI_KEY: your provider credential, stored outside the codebase.

The worker processes requests from the dashboard. It supports up to eight provider rounds per task and does not blindly retry interrupted changes. Requests use the provider's network/API service; accounts, model weights and any subscription are not bundled. No credentials or cloud calls were used during development verification. Self-improvement is initiated by a user task and creates actual code revisions, not unbounded background rewriting.

Speaker output uses browser speech synthesis. Microphone transcription uses browser SpeechRecognition where available, which can rely on the browser vendor's online service. Unsupported browsers display typing as the available input. Actual microphone/speaker devices need testing on the chosen laptop.

## Disk use and upgrades

Data directory:

- workspace/: user projects the AI can create and edit.
- revisions/: saved source/workspace ZIP revisions and metadata.
- tasks.json: persistent task history.
- activity.jsonl: tool names and success/failure history.

Revision restore replaces saved files and retains newly added files. Restart the relevant service after source changes. These are code revisions, not full-disk snapshots or bootable OS rollback images. Automatic signed OS update installation and no-USB disk conversion are separate unfinished components.
# Windows packaged client

The self-contained `FeatherMCP.exe` is built alongside `FeatherPrep.exe`. Point an MCP host's stdio server command at the full path to `FeatherMCP.exe`; no Python install is required. The MCP process starts the local read-only inventory and exposes Feather's tools. The host still needs to connect its own AI model.
