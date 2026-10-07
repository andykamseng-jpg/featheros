# Feather Local AI Core

## First local AI milestone

Feather can use an OpenAI-compatible model server running on the same computer. The local endpoint is configured from the desktop app and is restricted to loopback addresses (`localhost`, `127.0.0.1`, or `::1`). Feather sends task text and tool calls to this endpoint without an API key or a request to a cloud provider.

This is a connector foundation, not a bundled model runtime. It does not install a model, bundle or download weights, train a model, or guarantee a particular speed or quality. The local model server must already be running and support chat completions with function/tool calls. A later build can add model selection and benchmark-based sizing.

## Choosing the active provider

- If online and local providers are configured, Feather selects local AI by default.
- The user can explicitly select an online provider from the desktop app. If only one provider is configured, Feather uses it.
- Local and online provider configuration stays separate; this milestone does not silently send a failed local request to the online provider.
- When neither provider is configured, Feather continues to run its local hardware scan and agent without sending tasks to a model.
- Local setup persists only the non-secret endpoint and model name. Online credentials are held in memory for the current run and are not written to the local settings file.
- The Feather AI page keeps up to eight completed turns per conversation in local task history and sends that bounded history with subsequent turns. A new conversation starts a separate context.
- Local AI can search public web results, read bounded public HTTPS pages, and open a selected URL in the default browser. This first step cannot click page controls, fill or submit forms, or make purchases.

## Hardware profile

The `system_info` result reports RAM, logical processor count, available graphics names, a coarse resource band, and a local-model hint. The hint is deliberately cautious. It does not inspect GPU VRAM, benchmark inference speed, or identify an ideal model. Model fit remains benchmark-required on each target computer.

This milestone does not bundle or download model weights, and does not replace Windows. Feather Prep remains an app running inside Windows; booting FeatherOS and safely replacing Windows are future work.

## Next validation

1. Test a compact local model on a low-memory, CPU-only PC.
2. Measure response time, memory pressure, and tool-call reliability.
3. Test a larger local model on stronger hardware.
4. Only then define the minimum supported Feather Lite model and any full-local profile.

Feather Prep remains a Windows-side prototype. It does not yet boot FeatherOS or replace Windows.

