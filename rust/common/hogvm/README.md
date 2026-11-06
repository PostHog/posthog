# hogvm

A Rust implementation of the Hog virtual machine, at behavioral parity with the Node reference VM
(`@posthog/hogvm`, `common/hogvm/typescript`). Parity is enforced by `tests/parity.rs` (the full
program corpus, diffed against committed Node output) and `tests/stl_parity.rs` (per-STL cases).

## Execution modes

- **`sync_execute`** — synchronous, boolean/value-returning evaluation. This is what the production
  consumers use (`cymbal` error-tracking rule evaluation, `cohort-stream-processor`), and it is at
  parity with the reference VM, except under `with_boolean_text_equality`, which the cohort
  evaluator turns on to match ClickHouse.
- **`execute_resumable` / `resume`** — the suspendable-coroutine model for CDP hog functions
  (destinations): on a registered async function (`fetch`, `sleep`, …) the VM suspends and returns a
  serializable `VmSnapshot`; the host performs the side effect and resumes.

### Driving the VM from a host

A host can step `HogVM` itself instead of calling `sync_execute`, as the logs transformations in
`logs-ingestion` do to stop a program at a wall-clock deadline:

- `ExecutionContext::with_ordered_globals` takes globals as `OrderedJson`, whose objects keep their
  key order. `serde_json` sorts object keys, and the reference VM iterates a global object in
  JavaScript order, so `keys()` and `for (k, v in obj)` differ without it.
- `ExecutionContext::with_raw_result` keeps the finished value for `HogVM::take_result`, so the host
  reads it from the heap with its key order, and a value that JSON cannot hold does not fail the run.
- `HogVM::push_stack` answers a `StepOutcome::NativeCall` that the host handles itself.
- `HogVM::memory_bytes` is the heap plus the operand stack. Strings on the stack are outside the
  heap limit, so a host that must bound memory checks this after each native call.

## Node interop status (`VmSnapshot` / `VMState`)

The snapshot JSON is designed to be byte-compatible with the reference VM's `VMState` so a snapshot
can round-trip through either VM. **Rust↔Rust** round-trips are covered by `tests/async_resume.rs`.
Exchanging state with the **live Node VM** has known encoding gaps — tracked in
[#67272](https://github.com/PostHog/posthog/issues/67272), surfaced in review of
[#66631](https://github.com/PostHog/posthog/pull/66631):

1. **Tuples aren't flattened like Node.** Rust encodes tuples as `{"__hogTuple__": true, "items":
   [...]}`; Node's `getVMState` flattens them to bare arrays. A live tuple in a snapshot therefore
   doesn't survive a cross-VM round-trip.
2. **JSON number int/float ambiguity.** Rust deserializes an integer-valued JSON number (`5`) as an
   integer; Node always yields a float.
3. **Cumulative timeout not preserved across resume.** `drive_resumable` restarts the step counter
   each resume and hardcodes `sync_duration: 0`; Node bounds cumulative work by wall-clock across
   resumes.
4. **Header-inclusive ip for module chunks.** A snapshot taken while suspended inside an STL hog
   module (e.g. an async call within an `arrayMap` callback) would resume at the wrong ip in Node.

None of these affect the sync path — they only matter when exchanging `VMState` with the Node VM,
which is the live-Node cross-check follow-up.
