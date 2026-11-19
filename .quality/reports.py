"""Limit Mollify diagnostics to production paths; keep all project references."""

import json
import subprocess
from pathlib import Path


def in_scope(path: str, targets: list[str]) -> bool:
    location = Path(path)
    return any(location.is_relative_to(Path(target)) for target in targets)


def mollify(executable: Path, root: Path, targets: list[str], env: dict[str, str]):
    command = [
        str(executable),
        "dead-code",
        "--path",
        ".",
        "--format",
        "json",
        "--min-confidence",
        "uncertain",
    ]
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True)
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode not in {0, 1}:
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout)
    report = json.loads(result.stdout)
    if report.get("schema_version") != "0.1" or report.get("kind") != "dead-code":
        raise ValueError(
            "Mollify report schema changed; run the template upgrade controls"
        )
    if result.returncode == 1 and not report["summary"]["errors"]:
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout)
    findings = [
        item
        for item in report["findings"]
        if in_scope(item["location"]["path"], targets)
    ]
    for item in findings:
        location = item["location"]
        print(
            f"{location['path']}:{location['line']}: {item['rule']}: {item['reason']}"
        )
    print(
        f"Mollify: {len(findings)} production findings; "
        f"{report['summary']['files_analyzed']} files analyzed for references"
    )
    if any(item["severity"] == "error" for item in findings):
        raise SystemExit(1)
