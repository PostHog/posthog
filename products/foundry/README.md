# Foundry

Foundry is a bet portfolio: a hypothesis becomes a `Bet` with one success
metric, guardrails, and an append-only event log that carries it through
`drafted → funded → building → gated → exposed → verdict → archived`.
Integration safety comes from a machine gate (ReviewHog), knowledge transfer
from a git-backed memory repo, and consensus from the market — a feature
flag plus an experiment created the moment a bet is funded.

See `backend/` for the API (models, facade, presentation, Temporal
workflow) and `frontend/` for the portfolio and bet-detail scenes.

## Running a bet

The canonical way to drive a bet's lifecycle is the
[`/bet` Claude Code skill](../../.claude/skills/bet/SKILL.md) — create, fund,
check status, record a verdict, and list the portfolio, all from
conversation or from small non-interactive scripts, without reading this
product's code. It talks to the same REST API any external orchestrator
uses (`POST .../bets/`, `.../bets/:id/fund`, `.../bets/:id/events`,
`.../bets/:id/verdict`, `.../bets/:id/nodes`), authenticated with a personal
API key scoped to `bet:write` plus whatever the optional KPI-dashboard step
needs — see the skill's `references/setup.md` for the exact scope list and
how to mint one.
