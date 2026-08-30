"""Test bundled translations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.unit
def test_norwegian_translation_matches_english_structure() -> None:
    """Test Norwegian Bokmål covers every English translation key."""
    translation_dir = Path(__file__).parents[1] / "custom_components" / "openwrt_ubus" / "translations"
    english = json.loads((translation_dir / "en.json").read_text(encoding="utf-8"))
    norwegian = json.loads((translation_dir / "nb.json").read_text(encoding="utf-8"))

    def keys(value, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
        if not isinstance(value, dict):
            return {prefix}
        return {key for name, child in value.items() for key in keys(child, (*prefix, name))}

    assert keys(norwegian) == keys(english)
