"""Bounded hardware facts for AI planning; never a model-fit guarantee."""


def number(value, maximum=2**53 - 1):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if 0 <= result <= maximum else None


def rows(value, maximum=16):
    if isinstance(value, dict):
        return [value]
    return [v for v in value[:maximum] if isinstance(v, dict)] if isinstance(value, list) else []


def text(value):
    return str(value or "").strip()[:100]


def resource_profile(hardware):
    computers = rows(hardware.get("computer"))
    systems = rows(hardware.get("operating_system"))
    memory = number(computers[0].get("TotalPhysicalMemory")) if computers else None
    if memory is None:
        kib = number(hardware.get("memory_total_kib"), (2**53 - 1)//1024)
        memory = kib * 1024 if kib is not None else None
    free_kib = number(systems[0].get("FreePhysicalMemory"), (2**53 - 1)//1024) if systems else None
    processors = [{"name": text(p.get("Name")),
                   "cores": number(p.get("NumberOfCores"), 4096),
                   "logicalProcessors": number(p.get("NumberOfLogicalProcessors"), 8192)}
                  for p in rows(hardware.get("processors"))]
    if not processors and hardware.get("processor"):
        processors = [{"name": text(hardware["processor"]), "cores": None, "logicalProcessors": None}]
    return {
        "processors": processors,
        "memoryTotalBytes": memory,
        "memoryAvailableBytes": free_kib * 1024 if free_kib is not None else None,
        "graphics": [{"name": text(g.get("Name")), "reportedAdapterBytes": number(g.get("AdapterRAM"))}
                     for g in rows(hardware.get("graphics"))],
        "storage": [{"model": text(d.get("Model") or d.get("model")),
                     "sizeBytes": number(d.get("Size") or d.get("size_bytes"))}
                    for d in rows(hardware.get("disks"))],
        "modelFit": "benchmark_required",
        "graphicsMemoryNote": "Reported adapter memory may be incomplete and is not a usable VRAM budget; integrated graphics shares system RAM.",
    }
