"""Verify the i18n.js message catalog is complete across all supported languages.

t(key) silently falls back to the German catalog when a key is missing for
the current language (see i18n.js), so a language quietly missing a key (or
an entire feature's worth of keys, as happened once with the Statistics tab
for fr/es/it) is invisible at runtime and easy to miss by eye across ~1000
lines and 5 languages — these tests catch it mechanically instead.

i18n.js is a real ES module (uses `export const`), and there is no JS test
runner in this project (see CLAUDE.md — pytest is the only test tool). Rather
than hand-parsing the file with regex, these tests shell out to Node to
import it for real; the tests skip cleanly if Node isn't available.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_I18N_JS = Path(__file__).parent.parent.parent / "src" / "kudosy" / "static" / "i18n.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to load i18n.js as a real ES module",
)


def _load_i18n_module() -> dict[str, Any]:
    """Import i18n.js in Node and return {"SUPPORTED": [...], "MESSAGES": {...}}.

    Copied into a temp .mjs file first: Node picks CommonJS vs. ESM per the
    nearest package.json (there is none in this project), so importing a
    plain `.js` file containing `export const` would fail; `.mjs` always
    forces ESM regardless. A couple of browser-only globals the module's
    top-level code touches (localStorage, document.documentElement.lang) are
    stubbed — navigator is already provided by Node itself.
    """
    source = _I18N_JS.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        mjs_path = Path(tmp) / "i18n.mjs"
        mjs_path.write_text(source, encoding="utf-8")
        script = (
            "globalThis.localStorage = { getItem: () => null, setItem: () => {} };\n"
            "globalThis.document = { documentElement: {} };\n"
            f"const m = await import({json.dumps(mjs_path.as_uri())});\n"
            "console.log(JSON.stringify({ SUPPORTED: m.SUPPORTED, MESSAGES: m.MESSAGES }));\n"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert result.returncode == 0, f"node failed to import i18n.js:\n{result.stderr}"
    return json.loads(result.stdout)  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def i18n() -> dict[str, Any]:
    return _load_i18n_module()


def test_every_supported_language_has_a_message_block(i18n: dict[str, Any]) -> None:
    supported = i18n["SUPPORTED"]
    messages = i18n["MESSAGES"]
    missing = [lang for lang in supported if lang not in messages]
    assert not missing, f"SUPPORTED language(s) with no MESSAGES block at all: {missing}"


def test_no_message_block_outside_supported_languages(i18n: dict[str, Any]) -> None:
    """Catches a typo'd language code that would silently never be used."""
    supported = set(i18n["SUPPORTED"])
    extra = sorted(set(i18n["MESSAGES"].keys()) - supported)
    assert not extra, f"MESSAGES has language block(s) not listed in SUPPORTED: {extra}"


def test_every_language_defines_every_key(i18n: dict[str, Any]) -> None:
    """The core check: no language may be missing a key another one defines.

    Without this, a key added for German/English quietly falls back to
    German for fr/es/it forever (t() masks the gap silently).
    """
    messages = i18n["MESSAGES"]
    all_keys: set[str] = set()
    for keys in messages.values():
        all_keys.update(keys.keys())

    problems = []
    for lang, keys in messages.items():
        missing = sorted(all_keys - keys.keys())
        if missing:
            problems.append(f"{lang} is missing {len(missing)} key(s): {missing}")
    assert not problems, "Language(s) with missing i18n keys:\n" + "\n".join(problems)


def test_no_language_has_a_blank_translation(i18n: dict[str, Any]) -> None:
    """An empty string is effectively a missing translation."""
    messages = i18n["MESSAGES"]
    problems = []
    for lang, keys in messages.items():
        blank = sorted(k for k, v in keys.items() if isinstance(v, str) and v.strip() == "")
        if blank:
            problems.append(f"{lang} has empty value(s) for: {blank}")
    assert not problems, "Language(s) with blank translation values:\n" + "\n".join(problems)
