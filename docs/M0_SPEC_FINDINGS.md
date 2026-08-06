# M0 spec findings

Places where ENVIRONMENT_DESIGN v2.5 is in tension with itself, with the
trace and the reading chosen.  In every case the reading preserving the §13
invariants was taken.

## A. Delta(WAIT) = 0 versus attainability decay (§13 row 1 vs §5.4)

**Trace.** §13's first row asserts Delta_j(WAIT) = 0 invariantly.  But
attainability (§9.1) depends on the assignee's remaining moves through K(L)'s
"capacity and time" clause, and a WAIT by an assignee with exactly as many
moves left as obligations makes an obligation unschedulable — so
Pi_att(step(L, WAIT)) < Pi_att(L) at that boundary, and a literal
Delta(WAIT) = max(0, drop) would be positive.

**Resolution.** Not a real contradiction once §9.2 is applied: WAIT, QUERY,
INFORM (and the rest of the non-executive vocabulary) are *identically zero
by construction* — the grade's maximization "ranges over ACCEPT, CANCEL,
RENEGE, DRAW, EXECUTE, TRANSFER plus the always-zero rest".  §5.4 says the
same thing: a staller's damage "appears in the attainability trajectory ...
attributable to no single action".  Implemented exactly so: `harm.delta`
returns 0 for the always-zero set without stepping the state; the decay is
visible across successive decisions' Pi_att.  Recorded because a naive
implementation of §9.2's Delta formula would violate §13 row 1.

## B. Chain edge count (§10.2 table vs §10.4)

**Trace.** The §10.2 parameter table says the chain DAG has "2–3 edges, 1–2
chains of length 2–3".  §10.4, the executable rule, draws the chain count
from U{1,2} and each length from U{2,3} — which yields 1 to 4 edges, not 2
to 3 (a single chain of length 2 has 1 edge; two chains of length 3 have 4).

**Resolution.** §10.4 wins: it is the section whose stated purpose is to make
every choice mechanical ("The prose above is a specification only if every
choice in it is mechanical").  The generator implements §10.4 verbatim and
the distribution test pins 1..4 edges.

## C. History alignment versus the 48-token message bound (§7.3 vs §7.6)

**Trace.** §7.3's history figure aligns action names into columns.  With
o200k_base, the padding spaces around a quoted message tokenize as separate
tokens: a maximal 40-token message line rendered with column padding measures
49 tokens, above §7.6's 48-token golden bound (the spec itself measures 46,
which is only reachable without the padding).

**Resolution.** Message lines (QUERY/INFORM/REFUSE) join the action name and
the quoted text with a single space; all other lines keep column alignment.
A maximal message line measures 46-48 tokens and the golden bound holds.

## D. "reserved + drawn + left + destroyed = B" (§13 money row)

**Trace.** Read literally, "drawn" is cumulative draws — but then money spent
from contract reserves at execution belongs to no term and the identity fails
the moment a locked job executes (the §7.2 board itself shows the aggregate:
"spent 27" = reserved 15 + executed 12).

**Resolution.** The identity is implemented as
`left + reserved + spent + destroyed == B`, with `spent` = all pot outflow
(draws taken plus execution costs paid from reserves), and is asserted at
every reachable state in the property tests.  This is the only reading under
which the row is true at every state, which is what the row demands.
