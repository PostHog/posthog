### personhog-router context

### Requirements

- defines the API contract for all external personhog clients to consume
- provides a stateless/dependency-less routing path to personhog-replica pods
- participates in the handoff protocol to ensure requests are correctly and efficiently routed to personhog-leader pods
- scales horizontally through k8s
- accepts protobuf requests
- sends protobuf requests to respective BEs

### To Implement

- routers participate in handoff protocol/have vNode ownership awareness
- consistently/correctly/efficiently route requests to personhog-leader pods
- personhog-leader client installed on service to consume personhog-leader API
- define API contract that allows clients to consume strongly consistent/write to person state (consume personhog-leader BE capabilities)

### Implementation Details

#### personhog-replica routing

Routing decisions are made per-request in `src/router/routing.rs` based on two dimensions:
the data category and the consistency level from the request's `ReadOptions`.

Non-person data (hash key overrides, cohort membership, groups, group type mappings)
always routes to personhog-replica regardless of consistency level or operation type.
The replica service handles strong vs eventual consistency internally
by choosing the appropriate Postgres pool.

Person data (person, persondistinctid) checks the `ConsistencyLevel` on the request:

- `EVENTUAL` or unset → routes to personhog-replica
- `STRONG` → returns `UNIMPLEMENTED` (requires personhog-leader)
- Writes → returns `UNIMPLEMENTED` (requires personhog-leader)

#### personhog-leader routing

TBD
