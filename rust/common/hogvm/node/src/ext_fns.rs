//! The host functions the Node executor exposes to transformations, mirrored from
//! `nodejs/src/cdp/hog-transformations/transformation-functions.ts` (plus `print`, which the Node
//! VM surfaces as logs we don't compare).

use std::collections::HashMap;
use std::sync::OnceLock;

use hogvm::{construct_free_standing, native_func, HogLiteral, NativeFunction, VmError};
use serde_json::Value;

use crate::geoip;
use crate::logs;

static BOT_UA_LIST: OnceLock<Vec<String>> = OnceLock::new();
static BOT_IP_LIST: OnceLock<Vec<String>> = OnceLock::new();

// Mirrors MAX_DEPTH in transformation-functions.ts.
const CLEAN_NULL_VALUES_MAX_DEPTH: usize = 3;

/// Set once at `init`; later calls are ignored.
pub fn set_bot_lists(ua_list: Option<Vec<String>>, ip_list: Option<Vec<String>>) {
    if let Some(list) = ua_list {
        let _ = BOT_UA_LIST.set(list);
    }
    if let Some(list) = ip_list {
        let _ = BOT_IP_LIST.set(list);
    }
}

#[cfg(test)]
pub fn set_bot_lists_for_tests() {
    set_bot_lists(
        Some(vec!["googlebot".to_string()]),
        Some(vec!["1.2.3.4".to_string()]),
    );
}

// The `unsupported_ext_fn:` prefix is a contract with the Node callers
// (nodejs/src/cdp/hog-transformations/rust-vm.ts `isUnsupportedByRustVm`): it makes the executor
// hand the invocation to the Node VM and the shadow classify the comparison as skipped. Rephrasing
// it would turn those fallbacks into hard failures — change both sides together.
pub fn unsupported(name: &str) -> VmError {
    VmError::NativeCallFailed(format!("unsupported_ext_fn:{name}"))
}

pub fn transformation_ext_fns() -> HashMap<String, NativeFunction> {
    static EXT_FNS: OnceLock<HashMap<String, NativeFunction>> = OnceLock::new();
    EXT_FNS
        .get_or_init(|| {
            let mut fns: HashMap<String, NativeFunction> = HashMap::new();

            // Mirrors the Node executor's print handler: string args pass through, everything
            // else is JSON-serialized, joined with ", ".
            fns.insert(
                "print".to_string(),
                native_func(|vm, args| {
                    let mut parts: Vec<String> = Vec::with_capacity(args.len());
                    for arg in &args {
                        let part = match arg.deref(&vm.heap)? {
                            HogLiteral::String(value) => value.clone(),
                            _ => serde_json::to_string(&vm.hog_to_json(arg)?)
                                .map_err(|e| VmError::NativeCallFailed(e.to_string()))?,
                        };
                        parts.push(part);
                    }
                    logs::push(parts.join(", "));
                    Ok(HogLiteral::Null.into())
                }),
            );

            fns.insert(
                "geoipLookup".to_string(),
                native_func(|vm, args| {
                    if !geoip::is_initialized() {
                        return Err(unsupported("geoipLookup"));
                    }
                    let Some(arg) = args.first() else {
                        return Ok(HogLiteral::Null.into());
                    };
                    let HogLiteral::String(ip) = arg.deref(&vm.heap)? else {
                        return Ok(HogLiteral::Null.into());
                    };
                    match geoip::lookup(ip) {
                        Some(city) => construct_free_standing(city, 0),
                        None => Ok(HogLiteral::Null.into()),
                    }
                }),
            );

            fns.insert(
                "cleanNullValues".to_string(),
                native_func(|vm, args| {
                    let Some(arg) = args.first() else {
                        return Ok(HogLiteral::Null.into());
                    };
                    let value = vm.hog_to_json(arg)?;
                    construct_free_standing(clean_null_values(value, 1), 0)
                }),
            );

            fns.insert(
                "isKnownBotUserAgent".to_string(),
                native_func(|vm, args| {
                    let Some(list) = BOT_UA_LIST.get() else {
                        return Err(unsupported("isKnownBotUserAgent"));
                    };
                    let Some(arg) = args.first() else {
                        return Ok(HogLiteral::Boolean(false).into());
                    };
                    let HogLiteral::String(ua) = arg.deref(&vm.heap)? else {
                        return Ok(HogLiteral::Boolean(false).into());
                    };
                    let ua = ua.to_lowercase();
                    let known = list.iter().any(|bot| ua.contains(bot.as_str()));
                    Ok(HogLiteral::Boolean(known).into())
                }),
            );

            fns.insert(
                "isKnownBotIp".to_string(),
                native_func(|vm, args| {
                    let Some(list) = BOT_IP_LIST.get() else {
                        return Err(unsupported("isKnownBotIp"));
                    };
                    let Some(arg) = args.first() else {
                        return Ok(HogLiteral::Boolean(false).into());
                    };
                    let HogLiteral::String(ip) = arg.deref(&vm.heap)? else {
                        return Ok(HogLiteral::Boolean(false).into());
                    };
                    let known = list.iter().any(|known_ip| known_ip == ip);
                    Ok(HogLiteral::Boolean(known).into())
                }),
            );

            // Matches the Node executor: transformations may reference it, calling it throws.
            fns.insert(
                "postHogCapture".to_string(),
                native_func(|_vm, _args| {
                    Err(VmError::NativeCallFailed(
                        "posthogCapture is not supported in transformations".to_string(),
                    ))
                }),
            );

            fns.insert(
                "generateMessagingPreferencesUrl".to_string(),
                native_func(|_vm, _args| Err(unsupported("generateMessagingPreferencesUrl"))),
            );

            fns
        })
        .clone()
}

// Mirrors transformation-functions.ts cleanNullValuesInternal: strip nulls from arrays and
// objects, leave values past MAX_DEPTH untouched.
fn clean_null_values(value: Value, depth: usize) -> Value {
    if depth > CLEAN_NULL_VALUES_MAX_DEPTH {
        return value;
    }
    match value {
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .map(|item| clean_null_values(item, depth + 1))
                .filter(|item| !item.is_null())
                .collect(),
        ),
        Value::Object(entries) => Value::Object(
            entries
                .into_iter()
                .map(|(key, item)| (key, clean_null_values(item, depth + 1)))
                .filter(|(_, item)| !item.is_null())
                .collect(),
        ),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn clean_null_values_strips_null_entries_within_the_depth_budget() {
        // Mirrors the Node reference: a null child is dropped by its parent's filter even when the
        // child itself was visited past MAX_DEPTH, so nulls up to 4 levels deep are stripped.
        let input = json!({ "l2": { "l3": { "l4": null }, "keep": null } });
        assert_eq!(clean_null_values(input, 1), json!({ "l2": { "l3": {} } }));
    }

    #[test]
    fn clean_null_values_preserves_nulls_inside_containers_past_max_depth() {
        // The container at depth 4 is returned verbatim, so the null nested inside it survives.
        let input = json!({ "a": { "b": { "c": { "d": null } } } });
        assert_eq!(
            clean_null_values(input.clone(), 1),
            json!({ "a": { "b": { "c": { "d": null } } } })
        );
    }
}
