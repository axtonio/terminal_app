"""Build ast-grep rules from package paths, without parsing Python source."""

import json
import re
from pathlib import Path


def module_directories(
    root: Path, import_roots: list[str], targets: list[str], pattern: str
):
    packages = {}
    for target in targets:
        for init in (root / target).rglob(pattern):
            if any(
                part
                in {".venv", "venv", ".quality-venv", "site-packages", "__pycache__"}
                for part in init.parts
            ):
                continue
            for base in import_roots:
                try:
                    parts = init.parent.relative_to(root / base).parts
                except ValueError:
                    continue
                if parts and all(part.isidentifier() for part in parts):
                    packages[init.parent.relative_to(root).as_posix()] = parts
                    break
    return packages


def exact(names):
    return "^(" + "|".join(re.escape(name) for name in sorted(set(names))) + ")$"


def rule(identifier, match, files):
    return {
        "id": identifier,
        "language": "Python",
        "severity": "error",
        "message": "Import a concrete module, not a project package (__init__.py).",
        "files": files,
        "rule": match,
    }


def generate(root: Path, profile: dict, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    for previous in destination.glob("packages-*.yml"):
        previous.unlink()
    packages = module_directories(
        root, profile["import_roots"], profile["targets"], "__init__.py"
    )
    if not packages:
        return
    names = [".".join(parts) for parts in packages.values()]
    absolute = exact(names + [name + ".__init__" for name in names])
    rules = [
        rule(
            "no-package-imports",
            {
                "kind": "dotted_name",
                "regex": absolute,
                "any": [
                    {"inside": {"kind": "import_statement"}},
                    {
                        "inside": {
                            "kind": "aliased_import",
                            "field": "name",
                            "inside": {"kind": "import_statement"},
                        }
                    },
                    {
                        "inside": {
                            "kind": "import_from_statement",
                            "field": "module_name",
                        }
                    },
                ],
            },
            [target + "/**/*.py" for target in profile["targets"]],
        )
    ]
    # A relative import is resolved from its containing package. Scope each rule
    # to that exact directory, including newly added package __init__.py files.
    importers = module_directories(
        root, profile["import_roots"], profile["targets"], "*.py"
    )
    for index, (directory, importer) in enumerate(sorted(importers.items())):
        relative = set()
        for level in range(1, len(importer) + 1):
            base = importer[: len(importer) - level + 1]
            for target in packages.values():
                if target[: len(base)] == base:
                    suffix = ".".join(target[len(base) :])
                    name = "." * level + suffix
                    relative.add(name)
                    relative.add(name + ("." if suffix else "") + "__init__")
        if relative:
            rules.append(
                rule(
                    f"no-relative-package-imports-{index}",
                    {
                        "kind": "relative_import",
                        "regex": exact(relative),
                        "inside": {
                            "kind": "import_from_statement",
                            "field": "module_name",
                        },
                    },
                    [
                        path.relative_to(root).as_posix()
                        for path in sorted((root / directory).glob("*.py"))
                    ],
                )
            )
    for index, item in enumerate(rules):
        # JSON is a YAML subset accepted by ast-grep. No YAML dependency needed.
        (destination / f"packages-{index}.yml").write_text(
            json.dumps(item, indent=2) + "\n"
        )
