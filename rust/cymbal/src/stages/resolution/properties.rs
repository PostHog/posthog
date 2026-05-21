use serde_json::Value;

use crate::{
    error::UnhandledError,
    metric_consts::PROPERTIES_RESOLVER_OPERATOR,
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct PropertiesResolver;

impl ValueOperator for PropertiesResolver {
    type Item = ExceptionProperties;
    type Context = ResolutionStage;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        PROPERTIES_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut event: ExceptionProperties,
        _: ResolutionStage,
    ) -> OperatorResult<Self> {
        populate_derived_properties(&mut event);
        Ok(Ok(event))
    }
}

/// Compute every property Cymbal derives from `$exception_list` and write it onto the event.
///
/// Plural aggregates (`$exception_types`, `$exception_values`, `$exception_sources`,
/// `$exception_functions`) are always populated. Singular `$exception_type` and
/// `$exception_message` are backfilled from the first entry in `$exception_list` so that SQL,
/// MCP, and AI consumers can rely on the documented top-level property — SDKs leave those
/// singulars empty on the majority of events. `$exception_list` is the canonical source, so
/// any (occasionally malformed) value the client sent is overwritten.
pub fn populate_derived_properties(event: &mut ExceptionProperties) {
    event.exception_functions = Some(event.exception_list.get_unique_functions());
    event.exception_sources = Some(event.exception_list.get_unique_sources());
    event.exception_types = Some(event.exception_list.get_unique_types());
    event.exception_messages = Some(event.exception_list.get_unique_messages());
    event.exception_releases = event.exception_list.get_release_map();
    event.exception_handled = Some(event.exception_list.get_is_handled());

    if let Some(first) = event.exception_list.first() {
        event.props.insert(
            "$exception_type".to_string(),
            Value::String(first.exception_type.clone()),
        );
        event.props.insert(
            "$exception_message".to_string(),
            Value::String(first.exception_message.clone()),
        );
    }
}

#[cfg(test)]
mod test {
    use serde_json::json;

    use super::*;
    use crate::types::event::AnyEvent;

    fn make_event_from_props(props: serde_json::Value) -> ExceptionProperties {
        let any_event = AnyEvent {
            uuid: uuid::Uuid::now_v7(),
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: "2026-05-21T00:00:00Z".to_string(),
            properties: props,
            others: Default::default(),
        };
        ExceptionProperties::try_from(any_event).unwrap()
    }

    #[test]
    fn populates_singular_fields_from_first_exception() {
        let mut event = make_event_from_props(json!({
            "$exception_list": [
                {"type": "TypeError", "value": "Cannot read property 'x' of undefined"},
                {"type": "Error", "value": "ignored second exception"}
            ]
        }));

        populate_derived_properties(&mut event);

        let serialized = serde_json::to_value(&event).unwrap();
        assert_eq!(
            serialized.get("$exception_type"),
            Some(&Value::String("TypeError".to_string())),
            "singular $exception_type must be derived from $exception_list[0].type"
        );
        assert_eq!(
            serialized.get("$exception_message"),
            Some(&Value::String(
                "Cannot read property 'x' of undefined".to_string()
            )),
            "singular $exception_message must be derived from $exception_list[0].value"
        );

        let plural_types = serialized
            .get("$exception_types")
            .and_then(Value::as_array)
            .expect("$exception_types should be a populated array");
        assert!(plural_types.contains(&Value::String("TypeError".to_string())));
        assert!(plural_types.contains(&Value::String("Error".to_string())));

        let plural_values = serialized
            .get("$exception_values")
            .and_then(Value::as_array)
            .expect("$exception_values should be a populated array");
        assert!(plural_values.contains(&Value::String(
            "Cannot read property 'x' of undefined".to_string()
        )));
    }

    #[test]
    fn overwrites_malformed_singular_fields_sent_by_sdk() {
        // Some SDKs have been observed sending non-string values (`{}`) for these fields,
        // see frontend/src/lib/components/Errors/utils.ts. Cymbal must replace them with the
        // string derived from $exception_list rather than leaving the broken value in place.
        let mut event = make_event_from_props(json!({
            "$exception_list": [
                {"type": "ReferenceError", "value": "x is not defined"}
            ],
            "$exception_type": {},
            "$exception_message": {}
        }));

        populate_derived_properties(&mut event);

        let serialized = serde_json::to_value(&event).unwrap();
        assert_eq!(
            serialized.get("$exception_type"),
            Some(&Value::String("ReferenceError".to_string()))
        );
        assert_eq!(
            serialized.get("$exception_message"),
            Some(&Value::String("x is not defined".to_string()))
        );
    }
}
