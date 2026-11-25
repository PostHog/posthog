# meep-workflows

Copy this directory and add it as a Cargo path dependency. On a native target, parse the workflow JSON with `Workflow::parse`, implement `runner::Host` for the operations your application supports, and await `runner::run`. Each run returns its result and per-step trace. Clone its `Control` to cancel it.

Run `cargo run --example in_memory` for a complete example with an in-memory state patch and a host service call. Scheduling and recurrence calculations are available in `schedules`. The application owns persistence, waking scheduled runs and permission checks on host requests.

An event trigger such as `{"kind":"event","event":"taskMoved","filter":{"column":"done"}}` runs when every filter field equals the corresponding payload field. Omit the filter to accept every event of that name. A topic host calls `matches(&workflow.trigger, event_name, &payload)` before starting a run.

For a foreground-only embedding, give each mounted view a `catalog::ManualCatalog`. It handles register, compare-and-swap updates and run bookkeeping in memory. Dispatch source requests through the application’s existing scoped host. [Working example and provider contract](../../../docs/workflows.md)
