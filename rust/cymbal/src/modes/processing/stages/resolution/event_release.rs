use std::collections::HashMap;

use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    frames::releases::{mobile_release_hash_id, ReleaseRecord},
    metric_consts::EVENT_RELEASE_RESOLVER_OPERATOR,
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        exception_event::{ExceptionEvent, Parsed},
        operator::{OperatorResult, ValueOperator},
    },
};

/// Resolves the event-level release without going through the per-frame symbol-set join, so the
/// release is independent of which chunks resolved the stack.
///
/// Two sources, in order of preference:
///   1. `$release_id` — web builds inject the release row's id, which the SDK emits verbatim. Direct
///      foreign-key lookup.
///   2. app metadata — mobile SDKs inject nothing, but every event already carries `$app_namespace`,
///      `$app_version`, and `$app_build`, which the CLI hashed into the release when it uploaded the
///      dSYMs. We reconstruct that hash and look the release up by it.
///
/// When neither resolves, the event release stays unset and the pipeline falls back to the
/// per-frame symbol-set join for legacy events.
#[derive(Clone, Default)]
pub struct EventReleaseResolver;

impl ValueOperator for EventReleaseResolver {
    type Context = ResolutionStage;
    type Item = ExceptionEvent<Parsed>;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        EVENT_RELEASE_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionEvent<Parsed>,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        // No pool means the remote resolution server, which never resolves event releases.
        let Some(pool) = ctx.posthog_pool.as_ref() else {
            return Ok(Ok(evt));
        };

        let release_id = evt
            .properties()
            .get("$release_id")
            .and_then(Value::as_str)
            .and_then(|id| Uuid::parse_str(id).ok());

        if let Some(release_id) = release_id {
            let record = ReleaseRecord::for_id(pool, release_id, evt.team_id())
                .await
                .map_err(UnhandledError::from)?;
            evt.set_event_release(record);
        } else if let Some(hash_id) = mobile_release_hash_from_props(evt.properties()) {
            let record = ReleaseRecord::for_hash(pool, &hash_id, evt.team_id())
                .await
                .map_err(UnhandledError::from)?;
            evt.set_event_release(record);
        }

        Ok(Ok(evt))
    }
}

/// Rebuild the release `hash_id` from a mobile event's app metadata. Returns `None` for events that
/// aren't from a mobile SDK (no `$app_namespace`) or lack any version info to key on.
///
/// `$app_build` arrives as a JSON number when the SDK parsed `CFBundleVersion` as an integer, so
/// accept a number or a string and render it the same way the CLI saw the raw plist value.
fn mobile_release_hash_from_props(props: &HashMap<String, Value>) -> Option<String> {
    let namespace = props.get("$app_namespace").and_then(Value::as_str)?;
    let version = props.get("$app_version").and_then(Value::as_str);
    let build = props.get("$app_build").and_then(scalar_to_string);
    mobile_release_hash_id(namespace, version, build.as_deref())
}

fn scalar_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn props(value: Value) -> HashMap<String, Value> {
        value
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    #[test]
    fn numeric_and_string_build_hash_identically() {
        // The iOS SDK parses a numeric CFBundleVersion into an Int, so `$app_build` arrives as a JSON
        // number. It must hash the same as its string form, since the CLI hashed the raw plist string.
        let from_number = mobile_release_hash_from_props(&props(json!({
            "$app_namespace": "com.app", "$app_version": "1.0", "$app_build": 1
        })));
        let from_string = mobile_release_hash_from_props(&props(json!({
            "$app_namespace": "com.app", "$app_version": "1.0", "$app_build": "1"
        })));
        assert!(from_number.is_some());
        assert_eq!(from_number, from_string);
    }

    #[test]
    fn non_mobile_event_yields_no_hash() {
        // No `$app_namespace` means it isn't a mobile SDK event, so there's nothing to resolve.
        assert_eq!(
            mobile_release_hash_from_props(&props(json!({"$app_version": "1.0"}))),
            None
        );
    }
}
