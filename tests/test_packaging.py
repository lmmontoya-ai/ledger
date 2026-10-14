"""The frozen data files resolve to the same bytes in every install mode.

In a checkout or an editable install `ledger._paths.DATA_ROOT` is the
repository root; in a regular install it is the packaged copy
`ledger/_data/`.  Either way every file under spec/ and banks/ must be
byte-identical to this checkout's.
"""
from pathlib import Path

from ledger._paths import DATA_ROOT

CHECKOUT = Path(__file__).resolve().parents[1]


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes().replace(b"\r\n", b"\n")
            for d in ("spec", "banks") for p in sorted((root / d).rglob("*"))
            if p.is_file()}


def test_data_root_has_the_checkout_bytes():
    ours, installed = _files(CHECKOUT), _files(DATA_ROOT)
    assert ours and set(ours) == set(installed)
    for name, data in ours.items():
        assert installed[name] == data, name
