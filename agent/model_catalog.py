"""Conservative local-model candidates based on the saved resource profile.

These estimates are for choosing a model to benchmark, not fit guarantees.
Model downloads and provider configuration always require a separate action.
"""

GIB = 1024 ** 3

# Approximate Ollama Q4 download sizes. Runtime memory also holds context and
# other processes, so the available-memory floor exceeds the weight size.
MODELS = (
    ("qwen2.5-coder:7b", "coding", 4.7, 12, 7),
    ("deepseek-r1:7b", "reasoning", 4.7, 12, 7),
    ("deepseek-r1:14b", "reasoning", 9.0, 24, 13),
    ("qwen3-coder:30b", "coding", 19.0, 32, 24),
    ("deepseek-r1:32b", "reasoning", 20.0, 40, 26),
)


def _bytes(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def candidates(profile, disk_free_bytes=None):
    """Return bounded advice without mistaking integrated GPU RAM for VRAM."""
    profile = profile if isinstance(profile, dict) else {}
    total = _bytes(profile.get("memoryTotalBytes"))
    available = _bytes(profile.get("memoryAvailableBytes"))
    disk_free = _bytes(disk_free_bytes)
    result = []
    for name, purpose, download_gb, total_gib, available_gib in MODELS:
        if disk_free is not None and disk_free < (download_gb + 2) * 1000 ** 3:
            readiness = "insufficient_disk"
            reason = "Free disk space is below the model download plus a 2 GB reserve."
        elif total is None or available is None:
            readiness = "measure_memory"
            reason = "Measure total and available RAM on this PC first."
        elif total < total_gib * GIB or available < available_gib * GIB:
            readiness = "unlikely"
            reason = "Current RAM is below this model's conservative trial threshold."
        else:
            readiness = "benchmark_required"
            reason = "Memory permits a trial; check disk space, speed, and tool calls locally."
        result.append({"name": name, "purpose": purpose, "downloadGB": download_gb,
                       "readiness": readiness, "reason": reason})
    return result
