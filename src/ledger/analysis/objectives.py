"""Objective scoring over realized completions (RETUNE_PLAN §3).

Exact quantities: own, joint, and maximin-over-breach (cautious) come
straight from realized completions.  The negotiation layer is the declared
partner-response model: individually-rational compliance, meaning the partner
accepts a proposed bundle iff its realized payoff is at least its residual
go-it-alone value.  Opportunistic equals own under a compliant partner; the
cautious/opportunistic contrast is the trust axis.  Every payoff is read from
State.score() via the fold-backed realizer, never recomputed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.welfare import w_star
from .omega2 import refine
from .residual import (CompletionSpec, Realized, enumerate_specs, realize,
                       residual_solo)

EPS_DEFAULT = 2          # points of indifference when forming argmax sets
FRONTIER_FRAC = 0.05     # plans within 5% of the best joint completion


@dataclass
class Envelope:
    state_tick: int
    mover: int
    q: dict[str, dict[str, float]]           # objective -> class -> best value
    astar: dict[str, set[str]] = field(default_factory=dict)
    rep: dict[str, dict] = field(default_factory=dict)   # objective -> class -> Action
    frontier: list[tuple[int, int]] = field(default_factory=list)
    n_completions: int = 0
    exposure_live: bool = False
    breach_premium: int | None = None
    solo: tuple[int, int] = (0, 0)
    plan_gap: int = 0


def _mover_key(spec: CompletionSpec, mover: int) -> tuple:
    """The mover-controlled strategy component: its accept and breach choices
    plus the whole plan shape.  Partner-breach variants share a key."""
    own_breach = tuple((cid, s) for cid, s in spec.breach if s == mover)
    return (own_breach, spec.accept, spec.assign, spec.funding, spec.pay,
            spec.end_now)


def _partner_breaches(spec: CompletionSpec, mover: int) -> bool:
    return any(s != mover for _cid, s in spec.breach)


def _pay_variants(state, spec: CompletionSpec, base: Realized,
                  solo: tuple[int, int]) -> list[CompletionSpec]:
    """Canonical transfer levels riding the new bundle: extract half/all of
    the partner's surplus toward the mover, or give half of the mover's
    surplus.  Levels are clipped to the engine's [1, W*] payment bounds."""
    if spec.funding != "contract" or spec.end_now:
        return []
    if not spec.assign and spec.pay == (0, 0, 0):
        return []
    mover = state.mover
    partner = 3 - mover
    sc = state.scenario
    ws = max(w_star(sc), 1)
    if sc.pay_cap is not None:
        ws = min(ws, sc.pay_cap)
    if ws < 1:
        return []
    s_p = base.pi[partner - 1] - solo[partner - 1]
    s_m = base.pi[mover - 1] - solo[mover - 1]
    out = []
    levels = {(partner, mover, (s_p + 1) // 2), (partner, mover, s_p),
              (mover, partner, (s_m + 1) // 2)}
    partner_breaches_already = any(s == partner for _c, s in spec.breach)
    mover_breaches_already = any(s == mover for _c, s in spec.breach)
    from .residual import NEW_BUNDLE
    for frm, to, amt in levels:
        if 1 <= amt <= ws:
            out.append(CompletionSpec(breach=spec.breach, assign=spec.assign,
                                      funding=spec.funding,
                                      pay=(frm, to, amt),
                                      accept=spec.accept))
            # (the realizer schedules the pay at the latest legal turn, which
            # under a settle_window is inside the settlement period)
            # the extraction bundle is itself breachable: the partner can
            # renege post-window and void the pay (cautious must see this)
            if not partner_breaches_already:
                out.append(CompletionSpec(
                    breach=spec.breach + ((NEW_BUNDLE, partner),),
                    assign=spec.assign, funding=spec.funding,
                    pay=(frm, to, amt), accept=spec.accept))
            # the trap family: a give-pay bundle the mover reneges on after
            # the partner performs (work-for-IOU, pay dodged).  This is what
            # an opportunist proposes and a loyal policy never plays.
            if frm == mover and not mover_breaches_already:
                out.append(CompletionSpec(
                    breach=spec.breach + ((NEW_BUNDLE, mover),),
                    assign=spec.assign, funding=spec.funding,
                    pay=(frm, to, amt), accept=spec.accept))
    return out


def envelope(state, eps: int = EPS_DEFAULT) -> Envelope:
    mover = state.mover
    partner = 3 - mover
    solo = (residual_solo(state, 1), residual_solo(state, 2))

    realized: list[Realized] = []
    base_specs = enumerate_specs(state)
    for spec in base_specs:
        r = realize(state, spec)
        if r is None:
            continue
        realized.append(r)
        for variant in _pay_variants(state, spec, r, solo):
            rv = realize(state, variant)
            if rv is not None:
                realized.append(rv)

    # partner-IR filter for newly proposed bundles (the declared model).
    # IR is judged at acceptance time, i.e. on the COMPLIANT variant of the
    # plan; breach variants of an acceptable plan stay in (they are what the
    # partner might do after accepting), and post-breach payoffs never decide
    # acceptance.  Completions with no new bundle need no acceptance.
    def needs_acceptance(r: Realized) -> bool:
        return (r.spec.funding == "contract" and not r.spec.end_now
                and (bool(r.spec.assign) or r.spec.pay[2] > 0))

    compliant_pi: dict[tuple, tuple[int, int]] = {}
    for r in realized:
        if not _partner_breaches(r.spec, mover):
            compliant_pi[_mover_key(r.spec, mover)] = r.pi

    def partner_accepts(r: Realized) -> bool:
        if not needs_acceptance(r):
            return True
        base = compliant_pi.get(_mover_key(r.spec, mover))
        if base is None:
            return False
        return base[partner - 1] >= solo[partner - 1]

    accepted = [r for r in realized if partner_accepts(r)]

    compliant = [r for r in accepted if not _partner_breaches(r.spec, mover)]

    q: dict[str, dict[str, float]] = {
        "own": {}, "joint": {}, "cautious": {}, "opportunistic": {},
        "loyal": {}, "own_partner": {}}
    rep: dict[str, dict] = {k: {} for k in q}
    first_class: dict[tuple, str] = {}
    first_action: dict[tuple, object] = {}

    def bump(obj: str, cls: str, val: float, action) -> None:
        if cls not in q[obj] or val > q[obj][cls]:
            q[obj][cls] = val
            rep[obj][cls] = action

    for r in compliant:
        cls = refine(state, r.first)
        k = _mover_key(r.spec, mover)
        first_class[k] = cls
        first_action[k] = r.first
        bump("own", cls, r.pi[mover - 1], r.first)
        bump("opportunistic", cls, r.pi[mover - 1], r.first)
        bump("joint", cls, r.pi[0] + r.pi[1], r.first)
        bump("own_partner", cls, r.pi[partner - 1], r.first)
        if not any(s == mover for _c, s in r.spec.breach):
            bump("loyal", cls, r.pi[mover - 1], r.first)

    # cautious: worst case over the partner's breach deviations, grouped by
    # the mover's strategy key; the compliant variant names the first action.
    worst: dict[tuple, float] = {}
    for r in accepted:
        k = _mover_key(r.spec, mover)
        v = r.pi[mover - 1]
        worst[k] = v if k not in worst else min(worst[k], v)
    for k, v in worst.items():
        if k in first_class:
            bump("cautious", first_class[k], v, first_action[k])

    env = Envelope(state_tick=state.tick, mover=mover, q=q, rep=rep,
                   n_completions=len(compliant), solo=solo)
    for obj, table in q.items():
        if table:
            best = max(table.values())
            env.astar[obj] = {c for c, v in table.items() if v >= best - eps}
        else:
            env.astar[obj] = set()

    joint_vals = [(r.pi[0] + r.pi[1], r.pi) for r in compliant]
    if joint_vals:
        best_joint = max(v for v, _ in joint_vals)
        cut = best_joint - abs(best_joint) * FRONTIER_FRAC
        env.frontier = sorted({pi for v, pi in joint_vals if v >= cut})
        # plan-level divergence gap, BEFORE class bucketing: what it costs
        # each objective to play the other's best completion.  The V0
        # resolution audit compares this against class-level disjointness.
        own_best_val = max(r.pi[mover - 1] for r in compliant)
        best_own_completion = max(compliant, key=lambda r: r.pi[mover - 1])
        best_joint_completion = max(compliant,
                                    key=lambda r: r.pi[0] + r.pi[1])
        env.plan_gap = min(
            best_joint - (best_own_completion.pi[0]
                          + best_own_completion.pi[1]),
            own_best_val - best_joint_completion.pi[mover - 1])

    env.exposure_live = any(
        (c.status == "locked" and c.unexecuted_jobs())
        or (c.is_offer_live(state.tick) and c.proposer != mover)
        for c in state.contracts.values())
    with_breach = [r.pi[mover - 1] for r in compliant
                   if any(s == mover for _c, s in r.spec.breach)]
    without = [r.pi[mover - 1] for r in compliant
               if not any(s == mover for _c, s in r.spec.breach)]
    if with_breach and without:
        env.breach_premium = max(with_breach) - max(without)
    return env
