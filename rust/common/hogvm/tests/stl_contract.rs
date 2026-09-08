//! The generated contract table (src/stl_spec.rs, from common/hogvm/spec/stl.json) and the actual
//! native STL must agree: a builtin this VM registers without a contract entry, or a contract entry
//! with no implementation behind it, is a drift between the spec and the code.

use std::collections::BTreeSet;

use hogvm::{stl_map, STL_ARITY};

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
