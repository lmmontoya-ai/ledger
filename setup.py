"""Build hook: ship spec/ and banks/ inside regular (non-editable) wheels.

All project metadata is in pyproject.toml.  The frozen data directories stay
at the repository root so their paths are stable; this copies them into the
built package as ledger/_data/ so a regular install works without a
checkout (see src/ledger/_paths.py).  Editable installs read the checkout.
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
DATA_DIRS = ("spec", "banks")


class BuildPyWithData(build_py):
    def run(self):
        super().run()
        if getattr(self, "editable_mode", False):
            return
        for name in DATA_DIRS:
            shutil.copytree(ROOT / name,
                            Path(self.build_lib) / "ledger" / "_data" / name,
                            dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildPyWithData})
