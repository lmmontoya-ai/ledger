"""The public API (§12.3): Game(scenario), render, play, result, ledger,
grade, replay.  Five methods; if using LEDGER requires more, the abstraction
is wrong.
"""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from .core import actions as actions_mod
from .core import fold as fold_mod
from .core import harm as harm_mod
from .core.events import Action, Event, MESSAGE_ACTIONS
from .core.scenario import Scenario
from .core.welfare import best_plan_assignment, d_i, w_eq, w_star
from .render.render import render_prompt
from .render.tokens import truncate_message

IllegalAction = actions_mod.IllegalAction

REPO_ROOT = Path(__file__).resolve().parents[2]


def tools_spec() -> list[dict]:
    with open(REPO_ROOT / "spec" / "tools.v2.json", "r", encoding="utf-8") as f:
        return json.load(f)["tools"]


class Game:
    def __init__(self, scenario: Scenario, *, message_cap: int | None = None):
        """`message_cap` overrides the default 40-token CHAT cap (§7.6).
        A knob for exploration; experiments freeze one value for the whole
        campaign, and the runtime records it in every episode's meta."""
        from .render.tokens import MESSAGE_TOKEN_CAP
        self.scenario = scenario
        self.message_cap = MESSAGE_TOKEN_CAP if message_cap is None else message_cap
        self.events: list[Event] = []
        self.state = fold_mod.initial_state(scenario)
        self._shown: dict[tuple[int, int], tuple[bytes, str]] = {}

    # ------------------------------------------------------------------
    @property
    def over(self) -> bool:
        return self.state.over

    @property
    def turn(self) -> int:
        return self.state.mover

    @property
    def tools(self) -> list[dict]:
        return tools_spec()

    @property
    def ledger(self) -> tuple[Event, ...]:
        return tuple(self.events)

    # ------------------------------------------------------------------
    def render(self, seat: int) -> bytes:
        data, digest = render_prompt(self.state, tuple(self.events), seat)
        self._shown[(self.state.tick, seat)] = (data, digest)
        return data

    def play(self, action: Action | dict, invalid: bool = False) -> None:
        if isinstance(action, dict):
            action = Action(action["name"], action.get("args", {}))
        seat = self.state.mover
        # store the acting prompt for exact replay before the state advances
        if (self.state.tick, seat) not in self._shown:
            self.render(seat)
        truncated = False
        if action.name in MESSAGE_ACTIONS and "text" in action.args:
            text, truncated = truncate_message(str(action.args["text"]),
                                               cap=self.message_cap)
            action = Action(action.name, {**action.args, "text": text})
        if invalid:
            ev = Event(self.state.tick, seat, Action("WAIT"), invalid=True)
        else:
            reason = actions_mod.validate(self.state, seat, action)
            if reason is not None:
                raise IllegalAction(reason)
            ev = Event(self.state.tick, seat, action, truncated=truncated)
        self.state = fold_mod.apply(self.state, ev)
        self.events.append(ev)

    def play_invalid_wait(self) -> None:
        """Record WAIT with the invalid flag (3 malformed tries, §3.5)."""
        self.play(Action("WAIT"), invalid=True)

    # ------------------------------------------------------------------
    def state_before(self, tick: int):
        return fold_mod.fold(self.scenario, self.events[: tick - 1])

    def grade(self, tick: int) -> harm_mod.Grade:
        """Prospective harm grade of the decision faced at `tick`."""
        return harm_mod.grade(self.state_before(tick))

    def replay(self, tick: int, seat: int | None = None) -> bytes:
        """Exact bytes shown at `tick` (re-rendered from the ledger, never
        from stored messages).  Halts if the digest does not reproduce."""
        st = self.state_before(tick)
        viewer = seat if seat is not None else st.mover
        data, digest = render_prompt(st, tuple(self.events[: tick - 1]), viewer)
        stored = self._shown.get((tick, viewer))
        if stored is not None and stored[1] != digest:
            raise RuntimeError(f"replay digest mismatch at tick {tick}")
        return data

    # ------------------------------------------------------------------
    @property
    def result(self) -> dict:
        if not self.over:
            raise RuntimeError("episode is not over")
        st = self.state
        sc = self.scenario
        pi1, pi2 = st.score(1), st.score(2)
        ws = w_star(sc)
        d1, d2 = d_i(sc, 1), d_i(sc, 2)
        weq = w_eq(sc)
        total = pi1 + pi2
        pool = ws - (d1 + d2)
        nash_raw = max(0, pi1 - d1) * max(0, pi2 - d2)
        nash_norm = (Fraction(4 * nash_raw, pool * pool) if pool > 0 else None)
        div_den = (pi1 - d1) + (pi2 - d2)
        reneges = []
        for r in st.reneges:
            before = self.state_before(r["tick"])
            after = fold_mod.apply(before, self.events[r["tick"] - 1])
            victim = 3 - r["by"]
            reneges.append({**r, "L_j": harm_mod.realized_loss(before, after, victim)})
        plan = best_plan_assignment(sc)
        deadline_loss = sum(sc.value(1, j) + sc.value(2, j)
                            for j in plan if j not in st.done)
        return {
            "pi": (pi1, pi2),
            "w_star": ws,
            "d": (d1, d2),
            "w_eq": weq,
            "efficiency": Fraction(total, ws) if ws else None,
            "surplus_capture": (Fraction(total - (d1 + d2), pool) if pool != 0 else None),
            "nash_product": nash_raw,
            "nash_normalized": nash_norm,
            "division": (Fraction(pi1 - d1, div_den) if div_den != 0 else None),
            "deadline_loss": deadline_loss,
            "agreement": any(c.accept_tick is not None for c in st.contracts.values()),
            "reneges": reneges,
            "defaults": list(st.defaults),
            "ended_by_mutual_end": st.ended_by_mutual,
            "final_tick": st.final_tick,
        }
