# Prototype: protect transactional email sends from email worker batch time

Throwaway. This branch is never merged. Only the decision moves on.

## Question

The email worker polls, claims SES tokens, dequeues a batch, and awaits the whole batch before it polls again (`nodejs/src/cdp/services/cyclotron-v2/worker-rate-limited.ts`, `runConsumerLoop`).
A transactional (`priority = 0`) job that becomes due while a batch runs waits for the rest of that batch.
Under a broadcast the batch gets long, so the wait gets long.
How should transactional sends be protected from that wait?

## Options

- **A. Fast lane in each email pod.** A second poll loop in the same worker reads only `priority = 0`, with a small batch, and runs only while a bulk batch is in flight. Same deployment, same event loop.
- **B. Fast email fleet.** A second deployment of the email worker that dequeues only `priority = 0`. The main fleet keeps taking priority 0 first, so it is the fallback when the fast fleet is down.
- **C. Fleet tuning.** Earlier HPA scale-up and a higher `minPods`. Charts only.
- **D. Smaller batches.** A smaller email `CONSUMER_BATCH_SIZE`. Blunt: more polls and claims per row.
- **E. Slot loop (follow-up).** Replace batch-at-a-time with a loop that keeps N rows in flight and dequeues as slots free up, with lanes as config. A, B and E become one worker with different config.

## Files

- `modules.json`, `modules.html`, `modules-*.png`: the module page (rungs 1 and 2).
- `fast-lane.mmd`, `stuck-pod.mmd` and renders: call paths for option A.
- `contract-sketch.md`: the worker and queue changes option A needs.
