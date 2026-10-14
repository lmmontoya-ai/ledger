"""Optional environment variants layered over the frozen core.

A variant adds scenario fields, prompt text, or scoring on top of
`ledger.core`, `ledger.render` and `ledger.runtime` without editing them.
Nothing outside `ledger.variants` imports a variant, so the default
environment behaves identically whether or not a variant is used.

    hidden_objectives   three private resources (cash, materials, standing)
                        and one privately assigned objective per seat.  This
                        is the Contracting environment studied in the paper.
"""
