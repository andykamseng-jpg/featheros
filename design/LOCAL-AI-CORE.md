# Feather Local AI Core

## First local AI milestone

Feather can use an OpenAI-compatible model server running on the same computer. The local endpoint is configured from the desktop app and is restricted to loopback addresses (`localhost`, `127.0.0.1`, or `::1`). Feather sends task text and tool calls to this endpoint without an API key or a request to a cloud provider.

This is a connector foundation, not a bundled model runtime. It does not install a model, download weights, train a model, or guarantee a particular speed or quality. The local model server must already be running and support chat completions with function/tool calls. A later build can add model selection, downloads, benchmarks, and automatic sizing.

## Choosing the active provider

- If a local endpoint is configured, Feather selects local AI by default.
- The user can select the configured online HTTPS provider from the desktop app.
- Local and online provider configuration stays separate; this milestone does not silently send a failed local request to the online provider.
- When neither provider is configured, Feather continues to run its local hardware scan and agent without sending tasks to a model.

## Hardware profile

The `system_info` result reports RAM, logical processor count, available graphics names, a coarse resource band, and a local-model hint. The hint is deliberately provisional. It does not inspect GPU VRAM, benchmark inference speed, or identify an ideal model. A model must be tested on each target computer before Feather recommends or chooses it automatically.

## Next validation

1. Test a compact local model on a low-memory, CPU-only PC.
2. Measure response time, memory pressure, and tool-call reliability.
3. Test a larger local model on stronger hardware.
4. Only then define the minimum supported Feather Lite model and any full-local profile.

Feather Prep remains a Windows-side prototype. It does not yet boot FeatherOS or replace Windows.

