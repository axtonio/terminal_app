"""Resolve editable type roots without treating installed packages as source paths."""

import importlib.util
import os
import site
import sysconfig
from pathlib import Path


def type_path(root, profile):
    installed = {
        Path(path).resolve()
        for path in [
            *(sysconfig.get_path(name) for name in ("purelib", "platlib")),
            *site.getsitepackages(),
            site.getusersitepackages(),
        ]
    }
    paths = [str(root / item) for item in profile["import_roots"]]
    for name in profile.get("type_dependencies", []):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            raise SystemExit(
                f"Install development dependency {name} before quality checks"
            )
        for location in spec.submodule_search_locations:
            path = Path(location).resolve().parent
            if not any(path.is_relative_to(site) for site in installed):
                paths.append(str(path))
    return os.pathsep.join(dict.fromkeys(paths))
