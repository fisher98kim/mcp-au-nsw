import json
import tomllib
from pathlib import Path

import pytest

from mcp_au_nsw.licences.server import REGISTERS

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = sorted((ROOT / "registry").glob("*.json"))


def _version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_one_entry_per_server():
    assert {p.stem for p in ENTRIES} == {"fuel", "transport", "roads", "licences"}


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.stem)
def test_entry_matches_package(path):
    entry = json.loads(path.read_text())
    package = entry["packages"][0]
    assert entry["name"] == f"io.github.fisher98kim/nsw-{path.stem}"
    assert entry["version"] == package["version"] == _version()
    assert package["packageArguments"] == [{"type": "positional", "value": path.stem, "valueHint": "server"}]
    assert len(entry["description"]) <= 100
    # The registry verifies PyPI ownership by finding this marker in the README.
    assert f"mcp-name: {entry['name']} " in (ROOT / "README.md").read_text()


def test_licences_entry_lists_every_register():
    entry = json.loads((ROOT / "registry" / "licences.json").read_text())
    names = {e["name"] for e in entry["packages"][0]["environmentVariables"]}
    expected = {f"NSW_{slug.upper()}_API_{part}" for slug in REGISTERS for part in ("KEY", "SECRET")}
    assert names == expected
