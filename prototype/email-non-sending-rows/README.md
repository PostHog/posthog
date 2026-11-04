# Prototype: email rows that never send

Throwaway. This branch holds the design diagrams for one question and is never merged:
how should email queue rows that will not send (paced by a per-workflow rate limit, held by the team cap, suppressed, skipped) stop spending SES tokens and email worker batch time?

- `modules.html`: the module page. Open it and switch between Target, Target + what it removes, and Today. `modules-*.png` are the same views.
- `design.md`: the settled design: decisions, call paths, contracts, follow-ups and the ADR. Option B won.
- `modules-round1.json`: the first round's page with the alternatives.

## Today

The email worker claims one token per visible row from the global SES bucket before it dequeues (`claimBatchLimit`).
`EmailService.executeSendEmail` then decides the outcome. A skip, a per-workflow park or a team cap hold returns without a send and refunds nothing.
A per-workflow park reserves a slot that is "a place in line, not a promise", so the row claims again when it wakes, and a late or out-of-order wake parks again.
Each park costs a dequeue, a batch slot, the pre-send lookups and an SES token.

## Options

- **A. Settle at the gate.** The rate-limited queue refunds one SES token for each result that did not reach SES (`queueInvocationResults` sees every result). Fixes the tokens only: parked rows still fill batches and park again.
- **B. Pace at routing, with prepaid slots.** When the hogflow worker routes a send to the email queue, it books the workflow slot and the limiter debits the token at booking time. The row is enqueued with `scheduled = slot`, so it stays invisible until then and is dequeued once. The email worker skips the workflow claim for a booked row. Slice B0 first: prepaid slots inside the email worker, so a row parks at most once.
- **C. Claim at the SES call.** Exact per-recipient accounting, but dequeue loses its pacing: with an empty bucket, dequeued rows either wait inside the batch (fast-lane batch time) or reschedule (churn).
- **D. Exclude parked rows from the claim.** B already does this, since a booked row is not visible.
