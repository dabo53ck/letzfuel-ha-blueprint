#!/usr/bin/env python3
"""Static checks for the blueprint and the documents that point at it.

Fast and dependency-light (PyYAML only). It catches what is easy to get wrong
by hand and what the behaviour tests cannot see:

* a missing or incomplete ``blueprint:`` metadata block,
* ``!input`` references without a matching declared input, and the reverse,
* tuning inputs without a default (only entity pickers may be required),
* a ``source_url`` that does not point at this file,
* README / docs links to blueprint files that do not exist,
* a blueprint version that disagrees with the newest CHANGELOG section.

Run: ``python scripts/validate_blueprints.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_DIR = ROOT / "blueprints"
REPO_URL = "https://github.com/dabo53ck/letzfuel-ha-blueprint"
DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]

# blueprints/automation/<folder>/<file>.yaml, plain or URL-encoded
BLUEPRINT_LINK = re.compile(
    r"blueprints(?:/|%2F)automation(?:/|%2F)([\w-]+)(?:/|%2F)([\w-]+\.yaml)"
)
VERSION_BADGE = re.compile(r"badge/version-(v[\w.]+(?:--[\w.]+)*)-")
CHANGELOG_HEADING = re.compile(r"^## \[(v[\w.-]+)\]", re.MULTILINE)


class Tagged:
    __slots__ = ("tag", "value")

    def __init__(self, tag: str, value: Any) -> None:
        self.tag = tag
        self.value = value


class BlueprintLoader(yaml.SafeLoader):
    """SafeLoader that keeps Home Assistant's custom tags instead of resolving them."""


for _tag in ("!input", "!secret", "!env_var", "!include"):
    BlueprintLoader.add_constructor(
        _tag, lambda loader, node: Tagged(node.tag, loader.construct_scalar(node))
    )


def declared_inputs(node: Any, found: dict[str, dict[str, Any]]) -> None:
    """Collect ``name -> definition``, descending into sections."""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if isinstance(value, dict) and "input" in value:
            declared_inputs(value["input"], found)
        else:
            found[key] = value or {}


def referenced_inputs(node: Any, refs: set[str]) -> None:
    if isinstance(node, Tagged):
        if node.tag == "!input":
            refs.add(node.value)
    elif isinstance(node, dict):
        for value in node.values():
            referenced_inputs(value, refs)
    elif isinstance(node, list):
        for item in node:
            referenced_inputs(item, refs)


def check_blueprint(path: Path) -> tuple[list[str], str | None]:
    """Return (errors, version from the description badge)."""
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)
    except yaml.YAMLError as err:
        return [f"YAML parse error: {err}"], None
    if not isinstance(data, dict) or not isinstance(data.get("blueprint"), dict):
        return ["missing top-level 'blueprint:' mapping"], None

    errors: list[str] = []
    meta = data["blueprint"]
    for key in ("name", "author", "domain", "description", "source_url"):
        if not meta.get(key):
            errors.append(f"blueprint.{key} is missing")
    if not (meta.get("homeassistant") or {}).get("min_version"):
        errors.append("blueprint.homeassistant.min_version is missing")

    expected_url = f"{REPO_URL}/blob/main/{path.relative_to(ROOT).as_posix()}"
    if meta.get("source_url") != expected_url:
        errors.append(f"source_url is {meta.get('source_url')!r}, expected {expected_url!r}")

    declared: dict[str, dict[str, Any]] = {}
    declared_inputs(meta.get("input") or {}, declared)
    referenced: set[str] = set()
    referenced_inputs({k: v for k, v in data.items() if k != "blueprint"}, referenced)

    for name in sorted(referenced - set(declared)):
        errors.append(f"!input {name} is not a declared input")
    for name in sorted(set(declared) - referenced):
        errors.append(f"input {name} is declared but never used")
    for name, definition in sorted(declared.items()):
        if not definition.get("name"):
            errors.append(f"input {name} has no name")
        selector = definition.get("selector") or {}
        if "default" not in definition and "entity" not in selector:
            errors.append(f"input {name} has no default (only entity pickers may be required)")

    badge = VERSION_BADGE.search(str(meta.get("description", "")))
    version = badge.group(1).replace("--", "-") if badge else None
    if version is None:
        errors.append("description has no version badge (badge/version-vX.Y.Z-blue)")
    return errors, version


def check_doc_links() -> list[str]:
    errors: list[str] = []
    for doc in DOCS:
        if not doc.exists():
            continue
        for match in BLUEPRINT_LINK.finditer(doc.read_text(encoding="utf-8")):
            target = BLUEPRINT_DIR / "automation" / match.group(1) / match.group(2)
            if not target.exists():
                errors.append(f"{doc.relative_to(ROOT)} links to {target.relative_to(ROOT)}, which does not exist")
    return errors


def check_changelog(version: str | None) -> list[str]:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.exists() or version is None:
        return []
    headings = CHANGELOG_HEADING.findall(changelog.read_text(encoding="utf-8"))
    if not headings:
        return ["CHANGELOG.md has no '## [vX.Y.Z]' section"]
    if headings[0] != version:
        return [f"blueprint version {version} != newest CHANGELOG section {headings[0]}"]
    return []


def main() -> int:
    files = sorted(BLUEPRINT_DIR.rglob("*.yaml"))
    if not files:
        print("no blueprints found", file=sys.stderr)
        return 1

    failed = False
    version: str | None = None
    for path in files:
        errors, version = check_blueprint(path)
        rel = path.relative_to(ROOT).as_posix()
        print(f"{'FAIL' if errors else 'ok  '} {rel}")
        for error in errors:
            print(f"  - {error}")
        failed |= bool(errors)

    for label, errors in (("doc links", check_doc_links()), ("changelog", check_changelog(version))):
        print(f"{'FAIL' if errors else 'ok  '} {label}")
        for error in errors:
            print(f"  - {error}")
        failed |= bool(errors)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
