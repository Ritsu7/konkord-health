#!/usr/bin/env python3
"""Build konkord-health, install it into a throwaway virtualenv, and smoke-test it.

Usage:
    python3 scripts/verify_package.py

Run from the repository root. Requires `build` to be installed
(`pip install --upgrade build`), and `python3 -m venv` to be available.

This mirrors a real end user doing `pip install konkord-health`: it never
imports the in-repo `src/konkord` directly, only the installed wheel in an
isolated venv, so it catches packaging bugs (e.g. missing dependencies) that
running tests against the source tree would miss.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = Path("/tmp/konkord_verify_venv")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, **kwargs)
    if result.returncode != 0:
        print(f"FAILED (exit {result.returncode}): {' '.join(cmd)}")
        sys.exit(result.returncode)
    return result


def main() -> None:
    # 1. Clean old build artifacts.
    for path in ("dist", "build"):
        shutil.rmtree(REPO_ROOT / path, ignore_errors=True)
    for egg_info in REPO_ROOT.glob("src/*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
    shutil.rmtree(VENV_DIR, ignore_errors=True)

    # 2. Build sdist + wheel.
    run([sys.executable, "-m", "build"])

    wheels = sorted((REPO_ROOT / "dist").glob("*.whl"))
    if not wheels:
        print("No wheel produced in dist/.")
        sys.exit(1)
    wheel = wheels[-1]
    print(f"Built wheel: {wheel.name}")

    # 3. Create a clean virtualenv.
    venv.create(VENV_DIR, with_pip=True)
    venv_python = VENV_DIR / "bin" / "python3"
    venv_konkord = VENV_DIR / "bin" / "konkord"

    # 4. Install the built wheel (not `pip install -e .`, not the source tree).
    run([str(venv_python), "-m", "pip", "install", "--quiet", str(wheel)])

    # 5. Smoke test: import the installed package.
    run([
        str(venv_python), "-c",
        "import konkord; print('import OK, version:', konkord.__version__)",
    ])

    # 6. Smoke test: CLI entry point + real compare.
    run([str(venv_konkord), "--help"])

    # `compare` intentionally exits 1 when the reconciliation result is FAIL
    # (not a packaging error), so don't treat a non-zero return code here as
    # a failure -- just confirm it produced a well-formed report.
    print(f"$ {venv_konkord} compare --source examples/lab.hl7 --target examples/observation-good.json")
    result = subprocess.run(
        [
            str(venv_konkord), "compare",
            "--source", str(REPO_ROOT / "examples" / "lab.hl7"),
            "--target", str(REPO_ROOT / "examples" / "observation-good.json"),
        ],
        cwd=REPO_ROOT, text=True, capture_output=True,
    )
    if result.returncode not in (0, 1):
        print(f"FAILED (unexpected exit {result.returncode}): {result.stderr}")
        sys.exit(result.returncode)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"FAILED: compare did not produce valid JSON output:\n{result.stdout}\n{result.stderr}")
        sys.exit(1)
    print(f"compare ran OK, report overall: {report.get('overall')}")

    print("\nAll checks passed: build, install, import, and CLI all work from a clean environment.")


if __name__ == "__main__":
    main()
