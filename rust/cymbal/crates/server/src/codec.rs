//! JSON codec for payloads inside the internal `CymbalStageRuntime` envelope.
//!
//! The public Node-facing API never sees these bytes. The remote stage envelope
//! carries explicit type IDs, so the codec can change without changing the
//! public ingestion API.

use serde::de::DeserializeOwned;
use serde::Serialize;

use cymbal_core::StageError;

pub(crate) fn encode_json_payload<T>(value: &T) -> Result<Vec<u8>, StageError>
where
    T: Serialize,
{
    serde_json::to_vec(value).map_err(|error| StageError::Internal(error.to_string()))
}

pub(crate) fn decode_json_payload<T>(payload: &[u8]) -> Result<T, StageError>
where
    T: DeserializeOwned,
{
    serde_json::from_slice(payload).map_err(|error| StageError::InvalidInput(error.to_string()))
}

#[cfg(test)]
mod tests {
    //! Forward-compatibility guard for the internal stage envelope.
    //!
    //! These tests pin the contract that `decode_json_payload` tolerates unknown
    //! fields on every `StagePayload` we round-trip across the wire. If anyone
    //! adds `#[serde(deny_unknown_fields)]` to one of these types, the matching
    //! `tolerates_unknown_field_in_*` test will start failing — that's the point.
    //!
    //! When new stage payload types are introduced, add a case here as well.

    use std::collections::HashMap;

    use cymbal_alerting::AlertingEvent;
    use cymbal_core::{Metadata, StageError, StagePayload};
    use cymbal_domain::{
        EventOutcome, EventResult, ExceptionProperties, InputEvent, RateLimitAllowedEvent,
        RateLimitDecision, RateLimitGateOutput,
    };
    use cymbal_grouping::GroupedEvent;
    use cymbal_resolution::ResolvedEvent;
    use serde::{de::DeserializeOwned, Serialize};
    use serde_json::{json, Value};

    use super::{decode_json_payload, encode_json_payload};

    fn input_event() -> InputEvent {
        InputEvent {
            event_id: "event-1".to_string(),
            team_id: 42,
            properties: ExceptionProperties::default(),
        }
    }

    fn resolved_event() -> ResolvedEvent {
        ResolvedEvent {
            event_id: "event-1".to_string(),
            team_id: 42,
            properties: ExceptionProperties::default(),
            metadata: Metadata::default(),
        }
    }

    fn grouped_event() -> GroupedEvent {
        GroupedEvent::from_resolved_event(resolved_event())
    }

    fn event_result() -> EventResult {
        EventResult {
            event_id: "event-1".to_string(),
            outcome: EventOutcome::Drop {
                reason: "test".to_string(),
            },
        }
    }

    fn rate_limit_allowed() -> RateLimitGateOutput {
        RateLimitGateOutput::Allowed(RateLimitAllowedEvent {
            event: input_event(),
            decision: RateLimitDecision::Allowed { team_id: 42 },
        })
    }

    fn rate_limit_terminal() -> RateLimitGateOutput {
        RateLimitGateOutput::Terminal(event_result())
    }

    fn alerting_event() -> AlertingEvent {
        AlertingEvent {
            result: event_result(),
            spike_alert_input: None,
        }
    }

    /// Re-encode `sample`, drop an unknown field into every object in the JSON
    /// tree, and verify it still decodes. Walking the whole tree catches both
    /// top-level structs and externally-tagged enum variant payloads.
    fn assert_tolerates_unknown_fields<T>(label: &str, sample: T)
    where
        T: Serialize + DeserializeOwned,
    {
        let bytes = encode_json_payload(&sample).unwrap_or_else(|error| {
            panic!("encode {label} failed: {error}");
        });
        let mut value: Value = serde_json::from_slice(&bytes).unwrap_or_else(|error| {
            panic!("re-parse {label} failed: {error}");
        });
        sprinkle_unknown_field(&mut value);
        let bytes = serde_json::to_vec(&value).unwrap();
        decode_json_payload::<T>(&bytes).unwrap_or_else(|error| {
            panic!(
                "decode {label} with unknown fields failed: {error} — \
                 codec must tolerate forward-compatible additions"
            );
        });
    }

    fn sprinkle_unknown_field(value: &mut Value) {
        match value {
            Value::Object(map) => {
                // Externally tagged enum wrappers must contain exactly one
                // variant key. Add fields to the variant payload below, not to
                // the wrapper itself, otherwise the JSON no longer represents a
                // valid enum value.
                let is_externally_tagged_enum = map.len() == 1
                    && map
                        .keys()
                        .next()
                        .and_then(|key| key.chars().next())
                        .is_some_and(|first| first.is_ascii_uppercase());

                if !is_externally_tagged_enum {
                    map.insert(
                        "__cymbal_codec_future_field__".to_string(),
                        json!("ignored"),
                    );
                }
                for child in map.values_mut() {
                    sprinkle_unknown_field(child);
                }
            }
            Value::Array(items) => {
                for child in items {
                    sprinkle_unknown_field(child);
                }
            }
            _ => {}
        }
    }

    #[test]
    fn tolerates_unknown_field_in_input_event() {
        assert_tolerates_unknown_fields(InputEvent::TYPE.name, input_event());
    }

    #[test]
    fn tolerates_unknown_field_in_resolved_event() {
        assert_tolerates_unknown_fields(ResolvedEvent::TYPE.name, resolved_event());
    }

    #[test]
    fn tolerates_unknown_field_in_grouped_event() {
        assert_tolerates_unknown_fields(GroupedEvent::TYPE.name, grouped_event());
    }

    #[test]
    fn tolerates_unknown_field_in_event_result() {
        assert_tolerates_unknown_fields(EventResult::TYPE.name, event_result());
    }

    #[test]
    fn tolerates_unknown_field_in_rate_limit_gate_output_allowed() {
        assert_tolerates_unknown_fields(RateLimitGateOutput::TYPE.name, rate_limit_allowed());
    }

    #[test]
    fn tolerates_unknown_field_in_rate_limit_gate_output_terminal() {
        assert_tolerates_unknown_fields(RateLimitGateOutput::TYPE.name, rate_limit_terminal());
    }

    #[test]
    fn tolerates_unknown_field_in_alerting_event() {
        assert_tolerates_unknown_fields(AlertingEvent::TYPE.name, alerting_event());
    }

    #[test]
    fn valid_json_payload_round_trips() {
        let event = input_event();

        let encoded = encode_json_payload(&event).unwrap();
        let decoded = decode_json_payload::<InputEvent>(&encoded).unwrap();

        assert_eq!(decoded, event);
    }

    #[test]
    fn malformed_json_payload_maps_to_invalid_input() {
        let error = decode_json_payload::<InputEvent>(br#"{"event_id":"event-1""#)
            .expect_err("malformed JSON should fail to decode");

        assert!(matches!(error, StageError::InvalidInput(message) if !message.is_empty()));
    }

    #[test]
    fn covers_every_known_stage_payload_type() {
        // Belt-and-braces: if a new `StagePayload` is added to the registry
        // without a matching forward-compat test here, this assertion makes the
        // omission obvious. Keep this list in sync with `known_contracts`.
        let covered: HashMap<&'static str, &'static str> = [
            (InputEvent::TYPE.name, "input_event"),
            (ResolvedEvent::TYPE.name, "resolved_event"),
            (GroupedEvent::TYPE.name, "grouped_event"),
            (EventResult::TYPE.name, "event_result"),
            (RateLimitGateOutput::TYPE.name, "rate_limit_gate_output"),
            (AlertingEvent::TYPE.name, "alerting_event"),
        ]
        .into_iter()
        .collect();
        assert_eq!(
            covered.len(),
            6,
            "update tolerates_unknown_field_in_* tests when adding new stage payloads"
        );
    }
}
