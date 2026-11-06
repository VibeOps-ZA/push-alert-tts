"""The AI memory: plain-language corrections sent to the LLM with every alert.

One correction per line in ``/config/push_alert_tts/ai_memory_<entry>.txt``.
Before every change the previous file is copied to
``/config/push_alert_tts/ai_memory_versions/`` (the newest
``AI_MEMORY_VERSIONS`` copies are kept), so a bad edit can be undone.

Plain functions: they run in Home Assistant's worker threads.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from .const import AI_MEMORY_LINE_MAX, AI_MEMORY_VERSIONS


def split_lines(text: str | None) -> list[str]:
    """Text box / file content -> clean memory lines (blank lines dropped)."""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if line:
            lines.append(line[:AI_MEMORY_LINE_MAX])
    return lines


def read_memory(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return split_lines(handle.read())


def write_memory(path: str, lines: list[str], versions_dir: str, now: datetime) -> None:
    """Save the memory, keeping a copy of the previous version first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.makedirs(versions_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        stamp = now.strftime("%Y%m%dT%H%M%S%f")
        shutil.copy2(path, os.path.join(versions_dir, f"{base}.{stamp}.txt"))
        old = sorted(f for f in os.listdir(versions_dir) if f.startswith(base + "."))
        for name in old[:-AI_MEMORY_VERSIONS]:
            os.remove(os.path.join(versions_dir, name))
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("".join(f"{line}\n" for line in lines))
    os.replace(tmp, path)
