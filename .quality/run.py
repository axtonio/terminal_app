"""Run the vendored quality profile using the active application's dependencies."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import venv
from pathlib import Path

from dependencies import type_path
from packages import generate
from reports import mollify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def environment():
    path = ROOT / ".quality-venv"
    if Path(sys.prefix).resolve() == path.resolve():
        raise SystemExit(
            "Activate the application's development environment before running make"
        )
    fingerprint = hashlib.sha256(
        (
            str(ROOT) + str(Path(sys.executable).resolve()) + sys.prefix + sys.version
        ).encode()
        + (HERE / "requirements.lock").read_bytes()
    ).hexdigest()
    stamp = path / ".installed"
    python = path / "bin/python"
    if not stamp.exists() or stamp.read_text() != fingerprint:
        # Rebuild if the base interpreter or lock changes; never alter the app env.
        venv.EnvBuilder(with_pip=True, system_site_packages=True, clear=True).create(
            path
        )
        # A venv created from another venv inherits the base Python site, not the
        # outer venv. Process that environment's .pth files too (editable installs).
        site = (
            path
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
        active_sites = sorted(
            {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
        )
        (site / "active-environment.pth").write_text(
            "import site; "
            + "; ".join(f"site.addsitedir({p!r})" for p in active_sites)
            + "\n"
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--ignore-installed",
                "--require-hashes",
                "-r",
                str(HERE / "requirements.lock"),
            ],
            check=True,
        )
        stamp.write_text(fingerprint)
    return path / "bin"


def run(command, env):
    print("+ " + " ".join(str(arg) for arg in command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main():
    action = sys.argv[1]
    if action not in {"quality", "format"}:
        raise SystemExit("Expected quality or format")
    profile = tomllib.loads((HERE / "project.toml").read_text())
    bindir = environment()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in profile["import_roots"])
    env["MYPYPATH"] = type_path(ROOT, profile)
    env["MOLLIFY_UPDATE_CHECK"] = "off"
    targets = profile["targets"]
    if action == "format":
        run(
            [
                str(bindir / "ruff"),
                "check",
                "--config",
                str(HERE / "ruff.toml"),
                "--select",
                "I",
                "--fix",
                *targets,
            ],
            env,
        )
        run(
            [str(bindir / "black"), "--config", str(HERE / "black.toml"), *targets], env
        )
        return
    commands = [
        ["black", "--check", "--config", str(HERE / "black.toml"), *targets],
        ["ruff", "check", "--config", str(HERE / "ruff.toml"), *targets],
        ["flake8", "--config", str(HERE / "flake8.ini"), *targets],
        ["pylint", "--rcfile", str(HERE / "pylint.toml"), *targets],
        ["mypy", "--config-file", str(HERE / "mypy.ini"), *targets],
        ["lint-imports", "--config", str(HERE / "contracts.ini"), "--no-cache"],
    ]
    for command in commands:
        run([str(bindir / command[0]), *command[1:]], env)
    with tempfile.TemporaryDirectory(prefix="python-quality-") as directory:
        rules = Path(directory) / "rules"
        rules.mkdir()
        shutil.copy(HERE / "imports.yml", rules / "imports.yml")
        generate(ROOT, profile, rules)
        config = Path(directory) / "sgconfig.yml"
        config.write_text(json.dumps({"ruleDirs": [str(rules)]}))
        run([str(bindir / "ast-grep"), "scan", "--config", str(config), *targets], env)
    mollify(bindir / "mollify", ROOT, targets, env)


if __name__ == "__main__":
    main()
