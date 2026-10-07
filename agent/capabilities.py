"""Conservative hardware hints for choosing a Feather AI runtime.

These are memory-based planning bands, not guarantees that a particular model
will fit or run well. Model selection must be confirmed by a local benchmark.
"""
import os


_GIB = 1024 ** 3


def _items(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _integer(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _memory_bytes(report):
    direct = _integer(report.get("memory_total_bytes"))
    if direct:
        return direct

    kib = _integer(report.get("memory_total_kib"))
    if kib:
        return kib * 1024

    for item in _items(report.get("computer")):
        direct = _integer(item.get("TotalPhysicalMemory") or item.get("total_physical_memory"))
        if direct:
            return direct

    modules = _items(report.get("memory_modules"))
    capacities = [_integer(item.get("Capacity") or item.get("capacity")) for item in modules]
    capacities = [value for value in capacities if value]
    if capacities:
        return sum(capacities)

    return None


def _cpu_threads(report, fallback=None):
    processors = _items(report.get("processors"))
    counts = [
        _integer(item.get("NumberOfLogicalProcessors") or item.get("logical_processors"))
        for item in processors
    ]
    counts = [value for value in counts if value]
    if counts:
        return sum(counts)
    return _integer(fallback) or _integer(os.cpu_count())


def _gpu_names(report):
    names = []
    for item in _items(report.get("graphics")):
        name = item.get("Name") or item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip()[:160])
    return names[:8]


def profile_hardware(report, cpu_threads=None):
    """Return normalized resource facts and a cautious local-model hint."""
    report = report if isinstance(report, dict) else {}
    memory = _memory_bytes(report)
    threads = _cpu_threads(report, cpu_threads)
    if memory is None:
        band, hint = "unknown", "needs_hardware_scan"
    elif memory < 8 * _GIB:
        band, hint = "lean", "online_or_tiny_local_candidate"
    elif memory < 16 * _GIB:
        band, hint = "standard", "small_local_candidate"
    else:
        band, hint = "expanded", "larger_local_candidate"

    return {
        "memory_bytes": memory,
        "cpu_threads": threads,
        "gpu_names": _gpu_names(report),
        "resource_band": band,
        "local_model_hint": hint,
        "fit_status": "benchmark_required",
    }

