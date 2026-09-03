"""One-shot: give this venv's Pillow a working libraqm on Windows.

WHY THIS EXISTS
---------------
Arabic captions depend on Pillow being able to shape text through libraqm
(HarfBuzz); CLAUDE.md hard rule 3 and `pipeline/captions.py` refuse to run
without `PIL.features.check("raqm") == True`. SETUP.md used to say Windows
Pillow wheels bundle raqm "out of the box" — that is no longer true:

  * PyPI Pillow WINDOWS wheels >= 12.2 dropped raqm support entirely.
  * Wheels 11.0-12.1 keep the raqm *loader* but load `libraqm.dll`
    dynamically at runtime, and a clean Windows box does not have it.

So on Windows we (a) keep Pillow < 12.2 (see requirements.txt) and (b) stage a
conda-forge libraqm DLL closure next to the venv and point Pillow's DLL search
at it via a generated `sitecustomize.py`. This script does (b), idempotently.

USAGE
-----
    .venv\\Scripts\\python.exe scripts\\setup_raqm_windows.py

No-op if raqm already works. Not needed on Linux/macOS (there you rebuild
Pillow from source with libraqm — see SETUP.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
from pathlib import Path

MICROMAMBA_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/latest/download/"
    "micromamba-win-64.exe"
)
SITECUSTOMIZE_MARKER = "# video-factory: libraqm DLL search path"

SITECUSTOMIZE_BODY = f'''{SITECUSTOMIZE_MARKER}
"""Put the staged libraqm DLL closure on the Windows DLL search path so
Pillow's dynamically-loaded libraqm resolves (see scripts/setup_raqm_windows.py).
Harmless / no-op off Windows and when the folder is absent."""
import os
import sys

if sys.platform == "win32":
    _raqm = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "raqm"
    )
    if os.path.isdir(_raqm):
        try:
            os.add_dll_directory(_raqm)          # LoadLibraryEx user-dir search
        except (OSError, AttributeError):
            pass
        os.environ["PATH"] = _raqm + os.pathsep + os.environ.get("PATH", "")
'''


def raqm_ok(python: str) -> bool:
    """True if `python` reports Pillow raqm available (fresh process so a newly
    written sitecustomize is picked up)."""
    out = subprocess.run(
        [python, "-c", "from PIL import features; print(features.check('raqm'))"],
        capture_output=True, text=True,
    )
    return out.stdout.strip() == "True"


def main() -> int:
    python = sys.executable
    venv_root = Path(sys.prefix)
    raqm_dir = venv_root / "raqm"
    site_packages = Path(sysconfig.get_path("purelib"))

    if sys.platform != "win32":
        print("Not Windows — rebuild Pillow from source with libraqm (see SETUP.md).")
        return 0

    if raqm_ok(python):
        print("raqm already available — nothing to do.")
        return 0

    print(f"raqm missing; staging a libraqm DLL closure into {raqm_dir}")
    with tempfile.TemporaryDirectory(prefix="raqm-build-") as tmp:
        tmp_path = Path(tmp)
        mm = tmp_path / "micromamba.exe"
        print("  downloading micromamba ...")
        try:
            urllib.request.urlretrieve(MICROMAMBA_URL, mm)
        except Exception as exc:  # noqa: BLE001 — surface a clear manual fallback
            print(f"  ERROR: could not download micromamba ({exc}).")
            print("  Manual fix: install a conda-forge 'libraqm' env and copy its")
            print("  Library/bin/*.dll into", raqm_dir, "(alias raqm-0.dll -> libraqm.dll).")
            return 1

        env_dir = tmp_path / "env"
        print("  resolving conda-forge libraqm closure (this downloads a few DLLs) ...")
        proc = subprocess.run(
            [str(mm), "create", "-p", str(env_dir), "-c", "conda-forge",
             "libraqm", "-y", "--no-rc"],
            env={**os.environ, "MAMBA_ROOT_PREFIX": str(tmp_path / "root")},
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print("  ERROR: micromamba could not create the libraqm env:")
            print(proc.stderr[-1500:])
            return 1

        bin_dir = env_dir / "Library" / "bin"
        dlls = list(bin_dir.glob("*.dll"))
        if not dlls:
            print(f"  ERROR: no DLLs found in {bin_dir}")
            return 1

        raqm_dir.mkdir(parents=True, exist_ok=True)
        for dll in dlls:
            shutil.copy2(dll, raqm_dir / dll.name)
        # Pillow calls LoadLibrary("libraqm"); conda ships raqm-0.dll.
        src = raqm_dir / "raqm-0.dll"
        if src.exists():
            for alias in ("libraqm.dll", "raqm.dll"):
                shutil.copy2(src, raqm_dir / alias)
        print(f"  staged {len(dlls)} DLLs (+libraqm.dll alias)")

    # Generate / extend sitecustomize so every venv python call finds the DLLs.
    sc = site_packages / "sitecustomize.py"
    if sc.exists():
        existing = sc.read_text(encoding="utf-8")
        if SITECUSTOMIZE_MARKER not in existing:
            sc.write_text(existing.rstrip() + "\n\n" + SITECUSTOMIZE_BODY, encoding="utf-8")
            print(f"  appended DLL-path bootstrap to existing {sc}")
        else:
            print(f"  sitecustomize already wired ({sc})")
    else:
        sc.write_text(SITECUSTOMIZE_BODY, encoding="utf-8")
        print(f"  wrote {sc}")

    if raqm_ok(python):
        print("OK: raqm is now available.")
        return 0
    print("STILL FAILING: check that Pillow is < 12.2 (pip install 'pillow<12.2').")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
