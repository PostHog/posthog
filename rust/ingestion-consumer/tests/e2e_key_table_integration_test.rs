//! Key-table arm of the e2e scheduler matrix. The shared suite lives in
//! `e2e_suite/`; the pin-stash arm is `e2e_integration_test.rs`.

use ingestion_consumer::scheduler::SchedulerKind;

const E2E_SCHEDULER: SchedulerKind = SchedulerKind::KeyTable;

#[path = "e2e_suite/mod.rs"]
mod e2e_suite;
