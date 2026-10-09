"""The version shown on the device page must match the released manifest."""

import json
from pathlib import Path

from custom_components.push_alert_tts.const import VERSION

MANIFEST = Path(__file__).parent.parent / "custom_components" / "push_alert_tts" / "manifest.json"


def test_version_matches_manifest() -> None:
    assert VERSION == json.loads(MANIFEST.read_text())["version"]
