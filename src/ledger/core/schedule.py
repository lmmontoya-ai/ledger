"""Greedy schedule simulation (§5.5, §10.4).

A plan / obligation set is schedule-feasible iff a greedy simulation — each
agent executing its jobs in chain-respecting order on its own remaining ticks,
drawing first where self-funded (two moves) — completes by D.  Greedy suffices
because there are no execution interactions beyond the chain DAG and tick
counts.
"""
from __future__ import annotations

from .scenario import Scenario


def greedy_schedule_feasible(
    scenario: Scenario,
    assign: dict[int, int],
    start_tick: int,
    done: frozenset[int] | set[int] = frozenset(),
    self_funded: frozenset[int] | set[int] = frozenset(),
) -> bool:
    """True iff every job in `assign` (job -> seat) can be executed by tick D,
    starting play at `start_tick`, given jobs in `done` already finished.

    Jobs in `self_funded` cost the executing agent two moves (DRAW then
    EXECUTE); the rest cost one.  A job whose prerequisite is neither done nor
    in the plan can never complete: infeasible.
    """
    pending = {j: s for j, s in assign.items() if j not in done}
    if not pending:
        return True
    for j in pending:
        for pre in scenario.prereqs[j - 1]:
            if pre not in done and pre not in pending:
                return False
    done_sim = set(done)
    drawn: set[int] = set()
    # number of pending descendants (transitive) within the plan, to prefer heads
    def n_dependents(job: int) -> int:
        count = 0
        for other in pending:
            stack = list(scenario.prereqs[other - 1])
            seen = set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                if x == job:
                    count += 1
                    break
                stack.extend(scenario.prereqs[x - 1])
        return count

    for tick in range(start_tick, scenario.D + 1):
        mover = scenario.mover_at(tick)
        mine = [j for j, s in pending.items() if s == mover]
        if not mine:
            continue
        ready = [j for j in mine
                 if all(pre in done_sim for pre in scenario.prereqs[j - 1])]
        if not ready:
            continue
        # prefer jobs other pending jobs depend on; tie-break by job number
        ready.sort(key=lambda j: (-n_dependents(j), j))
        j = ready[0]
        if j in self_funded and j not in drawn:
            drawn.add(j)          # this move is the DRAW
            continue
        done_sim.add(j)
        del pending[j]
        if not pending:
            return True
    return not pending
