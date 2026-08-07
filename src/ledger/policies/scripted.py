"""Scripted policies for testing and baselines (§13 integration).

A policy is called as policy(game, seat) -> Action, only when it is `seat`'s
turn.  All policies produce legal actions or WAIT.
"""
from __future__ import annotations

import random

from ..core import actions as actions_mod
from ..core.events import Action
from ..core.welfare import best_plan_assignment


def _legal(game, seat, action: Action) -> bool:
    return actions_mod.validate(game.state, seat, action) is None


def _first_legal(game, seat, actions) -> Action | None:
    for a in actions:
        if _legal(game, seat, a):
            return a
    return None


def _executable_jobs(game, seat) -> list[int]:
    return [j for j in game.scenario.jobs()
            if _legal(game, seat, Action("EXECUTE", {"job": j}))]


def _partner_offers(game, seat):
    return [c for c in game.state.contracts.values()
            if c.is_offer_live(game.state.tick) and c.proposer != seat]


def _my_obligations(game, seat) -> list[int]:
    out = []
    for c in game.state.contracts.values():
        out.extend(c.obligations_of(seat))
        out.extend(c.optional_jobs_of(seat))
    return out


def _greedy_solo(game, seat) -> Action:
    sc = game.scenario
    ex = _executable_jobs(game, seat)
    if ex:
        obligations = set(_my_obligations(game, seat))
        # obligations first (highest own value), then best value
        ex.sort(key=lambda j: (j not in obligations, -sc.value(seat, j), j))
        return Action("EXECUTE", {"job": ex[0]})
    for j in sorted(sc.jobs(), key=lambda j: (-sc.value(seat, j), j)):
        if sc.value(seat, j) <= 0:
            break
        a = Action("DRAW", {"amount": sc.cost(seat, j), "job": j})
        if _legal(game, seat, a):
            return a
    return Action("END")


def _propose_plan(game, seat, assign: dict[int, int]) -> Action | None:
    sc = game.scenario
    st = game.state
    live = set()
    for c in st.contracts.values():
        for s in (1, 2):
            live.update(c.executable_jobs_of(s))
    assign = {j: s for j, s in assign.items()
              if j not in st.done and j not in live
              and not (j in st.draw_funding and not st.draw_funding[j][2])}
    if not assign:
        return None
    contract = {
        "assign": {str(j): s for j, s in assign.items()},
        "fund": {str(j): sc.cost(s, j) for j, s in assign.items()},
        "pay": [],
        "expires": min(st.tick + 3, sc.D),
    }
    a = Action("PROPOSE", {"contract": contract})
    return a if _legal(game, seat, a) else None


class AlwaysCooperate:
    """Proposes the efficient plan, accepts partner offers, executes
    obligations, then ends."""

    def __call__(self, game, seat) -> Action:
        offer = _first_legal(game, seat,
                             [Action("ACCEPT", {"offer_id": c.cid})
                              for c in _partner_offers(game, seat)])
        if offer:
            return offer
        ex = _executable_jobs(game, seat)
        obligations = set(_my_obligations(game, seat))
        ex = [j for j in ex if j in obligations]
        if ex:
            return Action("EXECUTE", {"job": ex[0]})
        mine_open = not any(c.is_offer_live(game.state.tick) and c.proposer == seat
                            for c in game.state.contracts.values())
        if mine_open:
            a = _propose_plan(game, seat, best_plan_assignment(game.scenario))
            if a:
                return a
        if _my_obligations(game, seat):
            return Action("WAIT")
        return Action("END")


class AlwaysDefect:
    """Never contracts; rejects offers, reneges anything locked, plays solo."""

    def __call__(self, game, seat) -> Action:
        for c in game.state.contracts.values():
            a = Action("RENEGE", {"contract_id": c.cid})
            if c.obligations_of(seat) and _legal(game, seat, a):
                return a
        rej = _first_legal(game, seat,
                           [Action("REJECT", {"offer_id": c.cid})
                            for c in _partner_offers(game, seat)])
        if rej:
            return rej
        return _greedy_solo(game, seat)


class HoldUp:
    """Sets up the exposure contract, waits for the partner to sink the head,
    then reneges on the tail and plays solo (Appendix B's exploitative arc)."""

    def __call__(self, game, seat) -> Action:
        sc = game.scenario
        st = game.state
        exp = sc.exposure
        # renege the moment the partner is exposed
        for c in st.contracts.values():
            if c.status != "locked":
                continue
            partner_done = any(j in st.done and st.done[j][0] != seat for j in c.assign)
            mine_left = c.obligations_of(seat)
            a = Action("RENEGE", {"contract_id": c.cid})
            if partner_done and mine_left and _legal(game, seat, a):
                return a
        # accept any offer that assigns me a job the partner values enough to fund
        acc = _first_legal(game, seat,
                           [Action("ACCEPT", {"offer_id": c.cid})
                            for c in _partner_offers(game, seat)
                            if any(s == seat for s in c.assign.values())])
        if acc:
            return acc
        # otherwise propose the exposure contract myself (as breaker)
        if exp is not None and exp[1] == seat:
            vic, brk, head, tail = exp
            assign = {head: vic, tail: brk}
            for pre in sc.prereqs[head - 1]:
                assign[pre] = vic
            mine_open = any(c.is_offer_live(st.tick) and c.proposer == seat
                            for c in st.contracts.values())
            if not mine_open and tail not in st.done:
                a = _propose_plan(game, seat, assign)
                if a:
                    return a
        # if I hold locked obligations but partner has not sunk anything, wait
        if any(c.status == "locked" for c in st.contracts.values()):
            return Action("WAIT")
        return _greedy_solo(game, seat)


class GreedyOptimal:
    """Never negotiates; executes its residual optimum via draws."""

    def __call__(self, game, seat) -> Action:
        return _greedy_solo(game, seat)


class TitForTat:
    """Cooperates until the partner reneges, then defects."""

    def __call__(self, game, seat) -> Action:
        betrayed = any(r["by"] != seat for r in game.state.reneges)
        if not betrayed:
            return AlwaysCooperate()(game, seat)
        for c in game.state.contracts.values():
            a = Action("RENEGE", {"contract_id": c.cid})
            if c.obligations_of(seat) and _legal(game, seat, a):
                return a
        return _greedy_solo(game, seat)


class RandomLegal:
    """Uniform over a legal menu, seeded."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def __call__(self, game, seat) -> Action:
        from ..core.harm import legal_executive_actions
        menu = list(legal_executive_actions(game.state))
        menu.append(Action("WAIT"))
        menu.append(Action("CHAT", {"text": "which jobs matter most to you?"}))
        menu.append(Action("CHAT", {"text": "thinking about a deal."}))
        menu.append(Action("END"))
        for c in _partner_offers(game, seat):
            a = Action("REJECT", {"offer_id": c.cid})
            if _legal(game, seat, a):
                menu.append(a)
        # a simple random proposal
        sc = game.scenario
        j = self.rng.choice(list(sc.jobs()))
        s = self.rng.choice([1, 2])
        a = _propose_plan(game, seat, {j: s})
        if a is not None:
            menu.append(a)
        return self.rng.choice(menu)


POLICIES = {
    "always-cooperate": AlwaysCooperate,
    "always-defect": AlwaysDefect,
    "hold-up": HoldUp,
    "greedy-optimal": GreedyOptimal,
    "tit-for-tat": TitForTat,
    "random-legal": RandomLegal,
}


def run_episode(scenario, policy1, policy2, game_cls=None):
    """Play a full episode; returns the finished Game."""
    from ..game import Game, IllegalAction
    game = Game(scenario)
    policies = {1: policy1, 2: policy2}
    while not game.over:
        seat = game.turn
        action = policies[seat](game, seat)
        try:
            game.play(action)
        except IllegalAction:
            game.play(Action("WAIT"))
    return game
