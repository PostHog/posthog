//! `toDateTime`/`toUnixTimestamp` parse strings at millisecond precision, matching the reference
//! VM (luxon `fromISO(...).toSeconds()`). Preserving microseconds — as Python's
//! `datetime.timestamp()` does — made `toUnixTimestamp(toDateTime(event.timestamp))` diverge from
//! the Node shadow on any sub-millisecond timestamp (the dominant EU `result_mismatch` bucket).

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

const OP_CALL_GLOBAL: i64 = 2;
const OP_STRING: i64 = 32;
const OP_RETURN: i64 = 38;

fn unix_ts(input: &str) -> Value {
    let bc = vec![
        json!("_H"),
        json!(1),
        json!(OP_STRING),
        json!(input),
        json!(OP_CALL_GLOBAL),
        json!("toDateTime"),
        json!(1),
        json!(OP_CALL_GLOBAL),
        json!("toUnixTimestamp"),
        json!(1),
        json!(OP_RETURN),
    ];
    let program = Program::new(bc).expect("valid program");
    sync_execute(&ExecutionContext::with_defaults(program), false).expect("execution succeeds")
}

#[test]
fn sub_millisecond_precision_is_truncated_to_millis() {
    // Microseconds are dropped: `.123456` -> `.123`, matching luxon / JS `Date.parse`.
    assert_eq!(
        unix_ts("2026-07-07T12:00:00.123456Z"),
        json!(1783425600.123)
    );
    // Millisecond input is preserved exactly.
    assert_eq!(unix_ts("2026-07-07T12:00:00.123Z"), json!(1783425600.123));
    // Whole seconds stay whole.
    assert_eq!(unix_ts("2026-07-07T12:00:00Z"), json!(1783425600.0));
}
