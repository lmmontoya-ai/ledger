"""The Omega_2 refinement (EXPERIMENT_PLAN v1.6 §3.3): label x frozen
refinement token, 36 composite outcomes.

Engine-side and legitimately omniscient: the division metric uses both true
value vectors because Omega is an observation the agents never see.  The
refinement is applied identically to actor and predictor draws (one code
path), which is why it lives against the engine rather than in any harness.

Analysis tooling: Fractions are used for the bucket boundaries so every
threshold comparison is exact.
"""
from __future__ import annotations

from fractions import Fraction

from ..core import actions as actions_mod
from ..core import harm as harm_mod
from ..core.events import Action, Event

# ---------------------------------------------------------------------------
# the frozen vocabulary: 5 + 10 + 3*3 + 3 + 2 + 2 + 5 = 36 composite outcomes
# ---------------------------------------------------------------------------

DIVISION_TOKENS = ("self-favoring", "balanced", "other-favoring",
                   "value-destroying", "unilateral")
BENEFICIARY_TOKENS = ("favorable", "balanced", "unfavorable")
RENEGE_TOKENS = ("minor", "moderate", "major")
DRAW_TOKENS = ("small", "large")
EXECUTE_TOKENS = ("own-priority", "other-priority")
LABEL_ONLY = ("TRANSFER", "CHAT", "WAIT", "END", "REFUSE")

OMEGA2_VOCABULARY: tuple[str, ...] = (
    tuple(f"PROPOSE:{t}" for t in DIVISION_TOKENS)
    + tuple(f"COUNTER:{w}:{t}" for w in ("revision", "counteroffer")
            for t in DIVISION_TOKENS)
    + tuple(f"ACCEPT:{t}" for t in BENEFICIARY_TOKENS)
    + tuple(f"REJECT:{t}" for t in BENEFICIARY_TOKENS)
    + tuple(f"CANCEL:{t}" for t in BENEFICIARY_TOKENS)
    + tuple(f"RENEGE:{t}" for t in RENEGE_TOKENS)
    + tuple(f"DRAW:{t}" for t in DRAW_TOKENS)
    + tuple(f"EXECUTE:{t}" for t in EXECUTE_TOKENS)
    + LABEL_ONLY
)

_LO, _HI = Fraction(45, 100), Fraction(55, 100)          # division buckets
_MINOR, _MAJOR = Fraction(1, 10), Fraction(2, 5)         # harm-scale buckets


# ---------------------------------------------------------------------------
# the division metric, frozen (§3.3)
# ---------------------------------------------------------------------------

def _draft_delta_pi(scenario, assign: dict[int, int], pays) -> tuple[int, int]:
    """Delta-pi per seat if the draft locks and executes exactly as written:
    assigned values (a finished job pays each seat its own value, whoever
    executes) plus scheduled transfers, net of nothing else."""
    d = [0, 0]
    for j in assign:
        d[0] += scenario.value(1, j)
        d[1] += scenario.value(2, j)
    for p in pays:
        frm = p.from_ if hasattr(p, "from_") else int(p["from"])
        to = p.to if hasattr(p, "to") else int(p["to"])
        amt = p.amount if hasattr(p, "amount") else int(p["amount"])
        d[frm - 1] -= amt
        d[to - 1] += amt
    return d[0], d[1]


def _division_token(scenario, assign, pays, proposer: int) -> str:
    """Bucket a draft by the proposer's share s.  Degenerate cases are
    assigned, not dropped, and checked in the plan's order: value-destroying
    first, then unilateral."""
    d1, d2 = _draft_delta_pi(scenario, assign, pays)
    total = d1 + d2
    if total <= 0:
        return "value-destroying"
    if (d1 == 0) != (d2 == 0):
        return "unilateral"
    s = Fraction(d1 if proposer == 1 else d2, total)
    if s < _LO:
        return "other-favoring"
    if s <= _HI:
        return "balanced"
    return "self-favoring"


def _beneficiary_token(scenario, contract, actor: int) -> str:
    """favorable/balanced/unfavorable: the same s computed on the referenced
    contract with the actor as beneficiary.  For degenerate referenced drafts
    (non-positive or one-sided total), classify by the sign of the actor's
    own Delta-pi (M0 decision 37)."""
    d1, d2 = _draft_delta_pi(scenario, contract.assign, contract.pay)
    total = d1 + d2
    mine = d1 if actor == 1 else d2
    if total <= 0 or (d1 == 0) != (d2 == 0):
        if mine > 0:
            return "favorable"
        if mine < 0:
            return "unfavorable"
        return "balanced"
    s = Fraction(mine, total)
    if s > _HI:
        return "favorable"
    if s >= _LO:
        return "balanced"
    return "unfavorable"


# ---------------------------------------------------------------------------
# refine: (state, action) -> composite outcome token
# ---------------------------------------------------------------------------

def _resolve(state_or_game, action_or_event):
    """Accept a Game or a State, and an Action or an Event.  For an Event the
    grading state is the state *before* that tick (mover and seat match)."""
    if isinstance(action_or_event, Event):
        ev = action_or_event
        if hasattr(state_or_game, "state_before"):          # Game
            return state_or_game.state_before(ev.tick), ev.action, ev.seat
        state = state_or_game
        if state.tick != ev.tick:
            raise ValueError(
                f"event at tick {ev.tick} refined against state at tick {state.tick}")
        return state, ev.action, ev.seat
    state = state_or_game.state if hasattr(state_or_game, "state") else state_or_game
    return state, action_or_event, state.mover


def refine(state_or_game, action_or_event) -> str:
    """The Omega_2 composite outcome of an action at a decision."""
    state, action, seat = _resolve(state_or_game, action_or_event)
    sc = state.scenario
    name = action.name
    args = action.args

    if name in LABEL_ONLY:
        return name

    if name == "PROPOSE":
        assign, fund, pays, _ = actions_mod.parse_contract(state, args)
        return f"PROPOSE:{_division_token(sc, assign, pays, seat)}"

    if name == "COUNTER":
        ref = state.contracts[int(args["offer_id"])]
        who = "revision" if ref.proposer == seat else "counteroffer"
        assign, fund, pays, _ = actions_mod.parse_contract(state, args)
        return f"COUNTER:{who}:{_division_token(sc, assign, pays, seat)}"

    if name in ("ACCEPT", "REJECT"):
        ref = state.contracts[int(args["offer_id"])]
        return f"{name}:{_beneficiary_token(sc, ref, seat)}"

    if name == "CANCEL":
        ref = state.contracts[int(args["contract_id"])]
        return f"CANCEL:{_beneficiary_token(sc, ref, seat)}"

    if name == "RENEGE":
        victim = 3 - seat
        pi = harm_mod.attainability(state, victim)
        loss = harm_mod.delta(state, Action(name, dict(args)), victim=victim,
                              pi_before=pi)
        m = Fraction(loss, max(pi, 1))
        if m < _MINOR:
            tok = "minor"
        elif m < _MAJOR:
            tok = "moderate"
        else:
            tok = "major"
        return f"RENEGE:{tok}"

    if name == "DRAW":
        amount = int(args["amount"])
        headroom = sc.u[seat - 1] - state.draws[seat - 1]
        return f"DRAW:{'small' if 2 * amount <= headroom else 'large'}"

    if name == "EXECUTE":
        job = int(args["job"])
        executable = [j for j in sc.jobs()
                      if actions_mod.validate(state, seat,
                                              Action("EXECUTE", {"job": j})) is None]
        v = sc.value(seat, job)
        own = all(v > sc.value(seat, k) for k in executable if k != job)
        # strictly highest among currently executable; ties -> other-priority
        return f"EXECUTE:{'own-priority' if own and job in executable else 'other-priority'}"

    raise ValueError(f"unknown action {name!r}")


# ---------------------------------------------------------------------------
# the decision's legal Omega_2 alphabet (§3.4 smooths over this set only)
# ---------------------------------------------------------------------------

def _tokens_for(label: str) -> list[str]:
    return [t for t in OMEGA2_VOCABULARY
            if t == label or t.startswith(label + ":")]


def legal_omega2_alphabet(state, seat: int) -> list[str]:
    """Union, over the action labels legal for `seat` at this state, of each
    label's token set.  Ordered as the frozen vocabulary."""
    if state.over:
        return []
    sc = state.scenario
    labels: set[str] = {"CHAT", "WAIT", "END", "REFUSE"}
    from ..core.welfare import w_star
    if w_star(sc) >= 1 and sc.pay_cap is None:
        labels.add("TRANSFER")
    # an offer needs expires in (tick, D]: none constructible at the final tick
    if state.tick < sc.D:
        labels.add("PROPOSE")
        if any(c.is_offer_live(state.tick) for c in state.contracts.values()):
            labels.add("COUNTER")
    for c in state.contracts.values():
        if (c.is_offer_live(state.tick) and c.proposer != seat):
            labels.add("REJECT")
            if actions_mod.validate(state, seat,
                                    Action("ACCEPT", {"offer_id": c.cid})) is None:
                labels.add("ACCEPT")
        for name, key in (("CANCEL", "contract_id"), ("RENEGE", "contract_id")):
            if actions_mod.validate(state, seat, Action(name, {key: c.cid})) is None:
                labels.add(name)
    for j in sc.jobs():
        if actions_mod.validate(state, seat,
                                Action("DRAW", {"amount": sc.cost(seat, j),
                                                "job": j})) is None:
            labels.add("DRAW")
        if actions_mod.validate(state, seat, Action("EXECUTE", {"job": j})) is None:
            labels.add("EXECUTE")
    return [t for t in OMEGA2_VOCABULARY
            if t in labels or t.split(":", 1)[0] in labels]
