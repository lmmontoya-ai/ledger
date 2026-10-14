"""Where the frozen data files live.

`spec/` (action, tool and template definitions) and `banks/` (frozen
scenario banks) sit at the repository root.  In a source checkout or an
editable install they are read from there, exactly as before.  A regular
(non-editable) install has no checkout, so the build copies both directories
into the package as `ledger/_data/` (see setup.py) and they are read from
that copy instead.  The bytes are the same either way.
"""
from __future__ import annotations

from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_CHECKOUT = _PACKAGE.parents[1]          # src/ledger -> repository root
_PACKAGED = _PACKAGE / "_data"
_MARKER = Path("spec") / "actions.v2.json"


def _data_root() -> Path:
    for base in (_CHECKOUT, _PACKAGED):
        if (base / _MARKER).is_file():
            return base
    return _CHECKOUT                     # missing data fails where it is read


DATA_ROOT = _data_root()
