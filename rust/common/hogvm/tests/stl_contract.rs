//! The generated contract table (src/stl_spec.rs, from common/hogvm/spec/stl.json) and the actual
//! native STL must agree: a builtin this VM registers without a contract entry, or a contract entry
//! with no implementation behind it, is a drift between the spec and the code.

use std::collections::BTreeSet;

use hogvm::{native_func, stl_map, sync_execute, ExecutionContext, HogLiteral, Program, STL_ARITY};
use serde_json::json;

// Async builtins (dispatched via the suspension machinery, not the native fn map).
const ASYNC_BUILTINS: &[&str] = &["sleep"];

#[test]
fn contract_table_and_native_stl_agree() {
    let native: BTreeSet<String> = stl_map().keys().cloned().collect();
    let contract: BTreeSet<String> = STL_ARITY.keys().map(|s| s.to_string()).collect();

    let unimplemented: Vec<&String> = contract
        .iter()
        .filter(|name| !native.contains(*name) && !ASYNC_BUILTINS.contains(&name.as_str()))
        .collect();
    assert!(
        unimplemented.is_empty(),
        "spec marks these as implemented in rust, but the native STL lacks them: {unimplemented:?}"
    );

    let uncontracted: Vec<&String> = native
        .iter()
        .filter(|name| !contract.contains(*name))
        .collect();
    assert!(
        uncontracted.is_empty(),
        "native STL functions missing from common/hogvm/spec/stl.json: {uncontracted:?}"
    );
}

// The reference VM dispatches embedder-registered functions before the STL, without an arity
// check, so an override under a builtin name must escape the contract while the stock builtin
// stays held to it.
#[test]
fn ext_fn_override_escapes_the_contract_arity() {
    // lower('a', 'b') — one argument over the contract maximum
    let bytecode = vec![
        json!("_H"),
        json!(1),
        json!(32),
        json!("a"),
        json!(32),
        json!("b"),
        json!(2),
        json!("lower"),
        json!(2),
    ];

    let stock = ExecutionContext::with_defaults(Program::new(bytecode.clone()).unwrap());
    let stock_err = sync_execute(&stock, false).unwrap_err();
    assert_eq!(
        stock_err.error.to_string(),
        "Function lower requires at most 1 arguments"
    );

    let overridden = ExecutionContext::with_defaults(Program::new(bytecode).unwrap()).with_ext_fn(
        "lower".to_string(),
        native_func(|_, args| Ok(HogLiteral::from(args.len() as i64).into())),
    );
    let result = sync_execute(&overridden, false).expect("override must run unchecked");
    assert_eq!(result, json!(2));
}
