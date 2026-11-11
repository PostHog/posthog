# 0002: Each organization gets a fair share of recalculation capacity

Status: Accepted (2026-11-11).
The routing part of layer 4 lands with this ADR.
The autoscaling change of layer 4, and layers 1 to 3, land in later changes.
ADR 0001 (lanes by query path and cost) lands later; this ADR uses its lane term.

## Context

Experiment metric recalculation runs as a Temporal workflow that fans out one calc activity per metric.
A calc runs on a task queue.
The activity and precompute queues have a fixed slot count per region, so they cap how many recalculation queries run on ClickHouse at once.
The main recalculation queue runs the workflows and their short Postgres activities, and it autoscales on its backlog.
Before this change, calcs ran on the fixed-slot queues only for the organizations on the `experiment-recalculation-activity-queue` flag, and on the main queue for every other organization.

Inside a queue, Temporal hands out tasks in arrival order.
One organization that starts many runs, for example an agent that requests results for many experiments in a few minutes, fills every slot, and other organizations wait.
The Temporal namespace runs without task-queue fairness and without priority, so fairness is solved in the application.
This design does not rely on new ClickHouse limits per user.

ClickHouse capacity errors are retried with back-off, so retries also act as the priority mechanism.
The goal is that retries mean errors only, and that a full queue means a wait.

## Decision

1. Four defense layers.
   Each layer limits one place where an organization can take more than its share, and catches what the layer above lets through.

   | #   | Layer                   | Unit                                          | Over the limit                                     |
   | --- | ----------------------- | --------------------------------------------- | -------------------------------------------------- |
   | 1   | Organization start rate | runs per minute, per organization and trigger | the run waits as queued, not as an error           |
   | 2   | Run fan-out cap         | calcs in flight per run                       | the next calc of that run waits                    |
   | 3   | Organization fair share | weighted calcs in flight per lane             | the calc waits, and the wait uses no retry attempt |
   | 4   | Fixed calc pools        | slots per queue and region                    | queue backlog                                      |

   Layer 1 gives agents a lower rate than people.
   Layer 2 stops one wide run from filling a lane before layer 3 reacts.
   Layer 3 needs layer 4, because a share is a part of a fixed total.

2. Layer 4: every calc runs on a fixed-slot queue.
   `_calc_route` stays the one place that picks the queue, for every organization.
   Local development and single-queue mode collapse all the queues into one, so there the calc keeps the workflow's queue.
   The main queue keeps the workflows and their short activities, and it keeps autoscaling.
   Its autoscaling trigger moves from the activity backlog to the workflow and discovery backlog, in a separate deploy configuration change.

3. Layer 3: the share is weighted max-min and work-conserving.
   An organization's share of a lane is `max(floor, capacity / active organizations)`, weighted by calc cost.
   Slots that one organization does not use go to the others.
   The first weight separates precompute reads from direct scans; a predicted cost can replace it later.

4. Layer 3 mechanism: admission in the workflow, with a lease in Redis.
   Before each calc, the workflow calls a short admission activity on the main queue.
   The activity checks a weighted lease per lane and organization in Redis: one member per calc, with an expiry.
   When the organization is over its share, the workflow waits with a durable timer (`workflow.sleep`) and asks again.
   The calc releases its lease when it ends, and the expiry releases a lease that the calc did not release.
   One module owns the share rule and the lease store.

5. Two flags, for independent rollback.
   `experiment-recalculation-org-fair-share` gates the layer 3 wait.
   `experiment-recalculation-lanes` gates the lanes of ADR 0001.
   A bug in the share does not turn off the lanes, and the reverse.

6. Delivery order: layers 4 and 3 first, then layer 1, then layer 2.

## Alternatives considered

- Reject a calc inside the calc activity and let Temporal retry it later.
  Rejected: each rejection uses a retry attempt, and the calc already holds a worker slot while it is rejected.
  A wait in the workflow is a durable timer that is visible in history and holds no slot.
- An allocator workflow per region and lane, which grants slots by signals.
  Rejected: every calc depends on one busy workflow, with about two signals per calc and frequent continue-as-new.
  A stall of the allocator stops every calc in the region.
- Temporal task-queue fairness keys.
  This is the idiomatic answer, but the namespace runs without fairness for now.
  The admission sits behind one call in the workflow, so fairness keys can replace layer 3 later by removing that call.
- Shuffle sharding: several queues per lane, and each organization hashed to two of them.
  Rejected: no shared state, but the result is approximate, and each lane needs many more queues and workers.
- A static cap per organization.
  Rejected: it keeps slots idle when only one organization has work.
- Fair queuing with a dispatcher (deficit round robin or weighted fair queuing).
  Rejected: it needs a dispatcher that owns the queue, in place of Temporal.
- A token bucket per organization.
  Rejected as layer 3: it limits a rate, not the work in flight, and calcs take from seconds to minutes.
  It fits layer 1.
- A fixed workflow pool on the main queue, with no autoscaling.
  Rejected: workflows use no ClickHouse time, and a fixed pool caps runs for all organizations together, not per organization.
  Layer 1 caps runs per organization.

## Consequences

- All calc load sits on the fixed-slot queues, so the queue wait grows when the pools are full.
  A calc on those queues has no `schedule_to_close` budget, so a run past `_STALE_RECALC_THRESHOLD` stays active up to `_QUEUED_RECALC_CEILING`.
- A run that started before layer 4 keeps its old queue.
  The calc activity stays registered on the main queue until every such run has closed.
  A later change removes that registration.
- Discovery builds a query runner for every metric of every organization to pick the route.
  This adds gate checks to discovery, but no metric scan.
- The `experiment-recalculation-activity-queue` flag no longer selects the queue or the ClickHouse user.
  To roll back layer 4, revert the change; a flag change has no effect.
- Layer 3 adds one short activity and one timer to the workflow history for each wait round.
  The rounds must back off and have a cap, so that a long wait does not grow the history without limit.
- Layer 3 changes the workflow command sequence, so it needs a new patch marker and replay tests.
- The share unit (calcs or cost units) and the floor value are set when layer 3 lands.
