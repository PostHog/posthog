# Kafka Assigner Architecture

## High-level overview

The Kafka Assigner is a distributed coordination service that manages
Kafka topic-partition assignments across consumer instances.
It uses etcd for state storage, leader election, and watch-based coordination,
and exposes a gRPC streaming API to consumers.

```text
                          ┌──────────────────────────────────────────────┐
                          │              etcd cluster                    │
                          │                                              │
                          │  /kafka-assigner/{group}/                    │
                          │  ├── consumers/{name}    (leased)            │
                          │  ├── assignments/{topic}/{partition}         │
                          │  ├── handoffs/{topic}/{partition}            │
                          │  ├── config/topics/{topic}                   │
                          │  └── assigner/leader     (leased)            │
                          └─────────┬──────────────────┬─────────────────┘
                                    │                  │
                          watches & writes      watches & writes
                                    │                  │
                   ┌────────────────┴────┐     ┌───────┴────────────────┐
                   │  Assigner Leader    │     │  Assigner Follower     │
                   │                     │     │                        │
                   │  ┌───────────────┐  │     │  ┌──────────────────┐  │
                   │  │  Coordinator  │  │     │  │  gRPC Server     │  │
                   │  │  (rebalance)  │  │     │  │  + Relay only    │  │
                   │  ├───────────────┤  │     │  └──────────────────┘  │
                   │  │  gRPC Server  │  │     └───────┬────────────────┘
                   │  │  + Relay      │  │             │
                   │  └───────────────┘  │          gRPC stream
                   └───────┬─────────────┘             │
                           │                    ┌──────┴──────┐
                        gRPC stream             │ Consumer C  │
                           │                    └─────────────┘
                  ┌────────┴────────┐
                  │                 │
           ┌──────┴───────┐  ┌──────┴───────┐
           │  Consumer A  │  │  Consumer B  │
           └──────────────┘  └──────────────┘
```

Only the leader runs the coordinator loop (rebalancing, handoff completion).
All instances run the gRPC server and relay,
so consumers can connect to any instance.

---

## Crate structure

```text
rust/
├── common/assignment-coordination/     Reusable coordination primitives
│   ├── store.rs                         Generic EtcdStore (JSON helpers)
│   ├── leader_election.rs               CAS-based leader election
│   ├── strategy/
│   │   └── sticky_balanced.rs           Sticky balanced partition strategy
│   └── util.rs                          Handoff diffing, timestamps
│
├── kafka-assigner/                     Main service crate
│   ├── types.rs                         Domain models
│   ├── store.rs                         Kafka-specific etcd operations
│   ├── assigner.rs                      Coordinator loop (leader only)
│   ├── consumer_registry.rs             In-memory local consumer tracking
│   ├── error.rs                         Error types
│   └── grpc/
│       ├── server.rs                    Register / PartitionReady / PartitionReleased
│       ├── relay.rs                     Watch etcd → push events to consumers
│       └── convert.rs                   Proto ↔ domain conversions
│
└── kafka-assigner-proto/               gRPC / protobuf definitions
    └── build.rs                         tonic-build codegen
```

---

## gRPC protocol

```text
┌──────────┐                                       ┌──────────────┐
│ Consumer │                                       │   Assigner   │
└────┬─────┘                                       └──────┬───────┘
     │                                                    │
     │─── Register(consumer_name) ───────────────────────►│
     │                                                    │  grant etcd lease
     │                                                    │  write RegisteredConsumer
     │                                                    │  fetch current assignments
     │◄── stream: Assignment { assigned: [...] } ─────────│
     │                                                    │
     │         ... consumer processes partitions ...      │
     │                                                    │
     │◄── stream: Warm { partition, current_owner } ──────│  (new owner)
     │                                                    │
     │         ... consumer warms partition ...           │
     │                                                    │
     │─── PartitionReady(topic, partition) ──────────────►│
     │◄── PartitionReadyResponse ─────────────────────────│
     │                                                    │
     │◄── stream: Release { partition, new_owner } ───────│  (old owner)
     │                                                    │
     │         ... consumer drains partition ...          │
     │                                                    │
     │─── PartitionReleased(topic, partition) ───────────►│
     │◄── PartitionReleasedResponse ──────────────────────│
     │                                                    │
```

---

## Partition handoff state machine

When the coordinator rebalances and moves a partition from one consumer to another,
the handoff goes through a three-phase state machine:

```text
   Coordinator creates               New owner signals             Coordinator detects
   handoff entry                     warming complete              Ready, atomically:
         │                                 │                       - sets phase = Complete
         ▼                                 ▼                       - updates assignment owner
   ┌───────────┐    consumer warms   ┌───────────┐             ┌───────────┐
   │  Warming  │────────────────────►│   Ready   │────────────►│ Complete  │
   └───────────┘  PartitionReady()   └───────────┘   CAS txn   └───────────┘
                                                                      │
                                                           old owner releases
                                                          PartitionReleased()
                                                                      │
                                                                      ▼
                                                              ┌───────────────┐
                                                              │   (deleted)   │
                                                              └───────────────┘
```

**During handoff, both consumers temporarily hold the partition:**

- The old owner continues processing (no interruption until Release)
- The new owner warms up (catches up on state, builds caches, etc.)
- Only after the new owner is Ready does the old owner get told to Release

---

## Coordinator loop (leader only)

```text
                    ┌─────────────────────┐
                    │   Leader Election   │
                    │   (CAS on etcd)     │
                    └────────┬────────────┘
                             │ won election
                             ▼
              ┌──────────────────────────────┐
              │   Spawn concurrent watches   │
              └──────┬──────────────┬────────┘
                     │              │
        ┌────────────┴───┐    ┌─────┴─────────────┐
        │ Watch          │    │ Watch             │
        │ /consumers/*   │    │ /handoffs/*       │
        └────────┬───────┘    └──────┬────────────┘
                 │                   │
          debounce (1s)         on each event
                 │                   │
                 ▼                   ▼
        ┌────────────────┐   ┌───────────────────────┐
        │   Rebalance    │   │  Handle handoff       │
        │                │   │  phase transition     │
        │ 1. List Ready  │   │                       │
        │    consumers   │   │ Ready → CAS to        │
        │ 2. Run sticky  │   │   Complete + update   │
        │    balanced    │   │   assignment owner    │
        │    strategy    │   │                       │
        │ 3. Diff vs     │   │ Stale cleanup:        │
        │    current     │   │ - new owner dead →    │
        │ 4. Write       │   │   delete handoff      │
        │    assignments │   │ - old owner dead &    │
        │    + handoffs  │   │   Complete → delete   │
        └────────────────┘   └───────────────────────┘
```

---

## Sticky balanced assignment strategy

Given N partitions and M consumers, the strategy:

1. **Preserve** existing assignments where the owner is still active
2. **Collect** unassigned partitions (new, orphaned, from dead consumers)
3. **Calculate** target: each consumer gets `N/M` partitions, `N%M` consumers get +1
4. **Strip excess** from overloaded consumers into the unassigned pool
5. **Fill** underloaded consumers from the pool (emptiest first)

```text
Example: 10 partitions, 3 consumers (A, B, C)

Target: 3 each, 1 consumer gets +1 = [4, 3, 3]

Initial assignment (all new):
  A: [p0, p1, p2, p3]     4 partitions
  B: [p4, p5, p6]         3 partitions
  C: [p7, p8, p9]         3 partitions

Consumer C dies → rebalance with 2 consumers:
Target: 5 each = [5, 5]
  A: [p0, p1, p2, p3, p7]   kept 4, gained 1 from pool
  B: [p4, p5, p6, p8, p9]   kept 3, gained 2 from pool
                              ─── only 3 partitions moved ───
```

---

## Consumer lifecycle

```text
    Consumer process starts
              │
              ▼
    ┌───────────────────┐
    │  gRPC Register()  │──────── etcd lease granted (TTL 30s)
    └────────┬──────────┘         lease bound to consumer key
             │
             ▼
    ┌───────────────────┐
    │  Receive initial  │──────── snapshot of currently-owned partitions
    │  assignments      │
    └────────┬──────────┘
             │
             ▼
    ┌───────────────────┐
    │  Process events   │◄─────── stream: Assignment / Warm / Release
    │  from stream      │
    └────────┬──────────┘
             │
        ┌────┴────┐
        │         │
   graceful    crash
   shutdown       │
        │         ▼
        │    ┌──────────────────┐
        │    │  Keepalive fails │──── lease expires after TTL
        │    │  → lease revoked │     consumer key deleted
        │    └────────┬─────────┘     coordinator rebalances
        │             │
        ▼             ▼
    ┌────────────────────┐
    │  Consumer removed  │
    │  from etcd         │
    │  Partitions        │
    │  redistributed     │
    └────────────────────┘
```
