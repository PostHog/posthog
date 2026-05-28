//! HogVM execution wrapper (TDD §5.2, M8.a–c).
//!
//! Wraps `hogvm::sync_execute` (`rust/common/hogvm/src/vm.rs:903`) to evaluate compiled
//! cohort-filter bytecode against an event, building the globals dict via the Rust port of
//! `convertClickhouseRawEventToFilterGlobals`. Non-bool results coerce to `false`, matching
//! the Node consumer. Planned submodules (TDD §3):
//! - `executor` — wraps `hogvm::sync_execute`; surfaces unknown CALL_GLOBALs as a metric (PR 1.4)
//! - `globals`  — `ClickHouseRawEvent` → HogVM globals dict (M8.c port; PR 1.4)
