"""Limites do contêiner e escolha de threads para o modelo gerenciado."""
import os
from pathlib import Path


def memory_limit_mb():
    limits = []
    for name in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = int(Path(name).read_text().strip())
            if value < 1 << 60:
                limits.append(value // (1024 * 1024))
        except (OSError, ValueError):
            pass
    return min(limits) if limits else None


def cpu_limit_cores():
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max" and int(quota) > 0 and int(period) > 0:
            return int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0 and period > 0:
            return quota / period
    except (OSError, ValueError):
        pass
    return None


def inference_threads(settings):
    # A quota desta API não descreve o hardware de um servidor de IA remoto.
    if not settings.local_ai_autostart or not settings.local_ai_auto_threads:
        return settings.local_ai_threads
    quota = cpu_limit_cores()
    if quota is None:
        return settings.local_ai_threads
    threads = min(4, max(1, int(quota)))
    try:
        threads = min(threads, max(1, len(os.sched_getaffinity(0))))
    except (AttributeError, OSError):
        pass
    return threads
