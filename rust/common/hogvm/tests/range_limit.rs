//! A range past the heap limit must fail with OutOfResource before the VM builds it, not abort the process.

use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use serde_json::json;

const OP_CALL_GLOBAL: i64 = 2;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;

#[test]
fn range_past_the_heap_limit_is_refused_before_it_is_built() {
    // With no heap limit (usize::MAX), only an overflow check refuses a length whose byte size overflows.
    for (length, max_heap_size) in [(1_000_000_000_000_i64, 1024 * 1024), (i64::MAX, usize::MAX)] {
        let bc = vec![
            json!("_H"),
            json!(1),
            json!(OP_INTEGER),
            json!(length),
            json!(OP_CALL_GLOBAL),
            json!("range"),
            json!(1),
            json!(OP_RETURN),
        ];

        let program = Program::new(bc).expect("valid program");
        let ctx = ExecutionContext::with_defaults(program)
            .with_globals(json!({}))
            .with_max_heap_size(max_heap_size);
        let failure = sync_execute(&ctx, false).expect_err("range past the heap limit must fail");
        assert!(
            matches!(failure.error, VmError::OutOfResource(_)),
            "range({length}) with a {max_heap_size}-byte heap: expected OutOfResource, got {:?}",
            failure.error
        );
    }
}
