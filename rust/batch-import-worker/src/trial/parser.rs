use std::sync::Arc;

use anyhow::Error;
use chrono::Duration;
use common_types::InternallyCapturedEvent;
use serde::de::DeserializeOwned;
use serde_json::Value;

use crate::{
    context::AppContext,
    error::UserError,
    job::model::JobModel,
    parse::{
        content::{
            amplitude::AmplitudeEvent, captured::captured_parse_fn, mixpanel::MixpanelEvent,
            ContentType, TransformContext,
        },
        format::{
            newline_delim_lines, skip_geoip, FormatConfig, ParserFnFor, UserFacingParseError,
        },
    },
};

use super::TrialRecord;

/// Build the trial-mode parser for a claimed job: resolves the team token and
/// delegates to [`trial_parser`].
pub async fn build_trial_parser(
    model: &JobModel,
    context: Arc<AppContext>,
) -> Result<ParserFnFor<TrialRecord>, Error> {
    let transform_context = TransformContext {
        team_id: model.team_id,
        token: context.get_token_for_team_id(model.team_id).await?,
        job_id: model.id,
        identify_cache: context.identify_cache.clone(),
        group_cache: context.group_cache.clone(),
        import_events: model.import_config.import_events,
        generate_identify_events: model.import_config.generate_identify_events,
        generate_group_identify_events: model.import_config.generate_group_identify_events,
    };
    Ok(trial_parser(
        &model.import_config.data_format,
        transform_context,
    ))
}

/// The trial-mode parser: same source format and transforms as the real import
/// ([`FormatConfig::get_parser`]), but each source line becomes a
/// [`TrialRecord`] pairing the line with its outputs, and parse/transform
/// failures are recorded on the line instead of failing the chunk.
pub fn trial_parser(
    format: &FormatConfig,
    transform_context: TransformContext,
) -> ParserFnFor<TrialRecord> {
    let FormatConfig::JsonLines {
        skip_blanks,
        content,
    } = format;

    match content {
        ContentType::Mixpanel(config) => {
            let transform = MixpanelEvent::parse_fn(
                transform_context,
                config.skip_no_distinct_id,
                config
                    .timestamp_offset_seconds
                    .map(Duration::seconds)
                    .unwrap_or_default(),
                skip_geoip(),
            );
            Box::new(newline_delim_lines(
                *skip_blanks,
                trial_line_fn::<MixpanelEvent, _>(move |e| {
                    transform(e).map(|o| o.into_iter().collect())
                }),
            ))
        }
        ContentType::Amplitude => {
            let transform = AmplitudeEvent::parse_fn(transform_context, skip_geoip());
            Box::new(newline_delim_lines(
                *skip_blanks,
                trial_line_fn::<AmplitudeEvent, _>(transform),
            ))
        }
        ContentType::Captured => {
            let transform = captured_parse_fn(transform_context, skip_geoip());
            Box::new(newline_delim_lines(
                *skip_blanks,
                trial_line_fn::<common_types::RawEvent, _>(move |e| {
                    transform(e).map(|o| o.into_iter().collect())
                }),
            ))
        }
    }
}

/// Per-line trial parser: deserialize the line as `T`, run the import transform,
/// and fold any failure into the record's `error` instead of propagating it.
///
/// The one deliberate `Err` path is a parse failure on the chunk's trailing
/// remainder (`is_complete_line == false`): that is almost always a line split
/// at the chunk boundary, and returning `Err` leaves it unconsumed so the next
/// chunk re-reads it whole. The trade-off (matching the real import) is that a
/// genuinely corrupt final line without a trailing newline pauses the trial
/// instead of becoming an error record.
fn trial_line_fn<T, F>(transform: F) -> impl Fn(&str, bool) -> Result<TrialRecord, Error> + Sync
where
    T: DeserializeOwned + UserFacingParseError,
    F: Fn(T) -> Result<Vec<InternallyCapturedEvent>, Error> + Sync,
{
    move |line, is_complete_line| {
        let typed: T = match serde_json::from_str(line) {
            Ok(typed) => typed,
            Err(e) if !is_complete_line => {
                let user_msg = T::user_facing_parse_error(&e);
                return Err(Error::from(e).context(UserError::new(user_msg)));
            }
            Err(e) => {
                return Ok(TrialRecord {
                    source: source_value(line),
                    outputs: vec![],
                    error: Some(T::user_facing_parse_error(&e)),
                });
            }
        };

        let source = source_value(line);
        match transform(typed) {
            Ok(outputs) => Ok(TrialRecord {
                source,
                outputs: outputs.into_iter().map(Into::into).collect(),
                error: None,
            }),
            Err(e) => Ok(TrialRecord {
                source,
                outputs: vec![],
                error: Some(user_facing_transform_error(&e)),
            }),
        }
    }
}

/// The user-facing message for a transform failure. Transform errors describe
/// the user's own data, so when the chain carries no explicit [`UserError`] the
/// outermost message (e.g. "No distinct_id found") is the most specific safe
/// description we have — better than the generic unknown-error fallback.
fn user_facing_transform_error(e: &Error) -> String {
    match e.downcast_ref::<UserError>() {
        Some(user_error) => user_error.msg.clone(),
        None => e.to_string(),
    }
}

/// The source line as JSON when it is valid JSON (so the UI renders an object),
/// or the raw text otherwise.
fn source_value(line: &str) -> Value {
    serde_json::from_str(line).unwrap_or_else(|_| Value::String(line.to_string()))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use uuid::Uuid;

    use super::*;
    use crate::cache::{MockGroupCache, MockIdentifyCache};
    use crate::parse::content::ContentType;

    fn captured_trial_parser() -> ParserFnFor<TrialRecord> {
        let context = TransformContext {
            team_id: 1,
            token: "token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        };
        trial_parser(
            &FormatConfig::JsonLines {
                skip_blanks: true,
                content: ContentType::Captured,
            },
            context,
        )
    }

    fn valid_line(event: &str, distinct_id: &str) -> String {
        format!(
            r#"{{"event":"{event}","distinct_id":"{distinct_id}","timestamp":"2024-01-01T00:00:00Z","properties":{{}}}}"#
        )
    }

    #[test]
    fn records_pair_sources_with_outputs_and_tolerate_bad_lines() {
        let parser = captured_trial_parser();
        let chunk = [
            valid_line("first", "u1"),
            "{not json".to_string(),
            r#"{"distinct_id":"u2"}"#.to_string(), // missing `event`
            r#"{"event":"orphan","properties":{}}"#.to_string(), // no distinct_id -> transform error
            valid_line("last", "u3"),
        ]
        .join("\n")
            + "\n";

        let parsed = parser(chunk.clone().into_bytes()).unwrap();

        assert_eq!(parsed.consumed, chunk.len());
        assert_eq!(parsed.data.len(), 5);

        let ok = &parsed.data[0];
        assert_eq!(ok.error, None);
        assert_eq!(ok.outputs.len(), 1);
        assert_eq!(ok.outputs[0].event, "first");
        assert_eq!(ok.outputs[0].distinct_id, "u1");
        assert_eq!(ok.source["event"], "first");

        let syntax = &parsed.data[1];
        assert!(syntax.outputs.is_empty());
        assert!(syntax.error.is_some());
        // An unparseable line is preserved as raw text
        assert_eq!(syntax.source, Value::String("{not json".to_string()));

        let schema = &parsed.data[2];
        assert!(schema
            .error
            .as_deref()
            .unwrap()
            .contains("Missing required field 'event'"));
        assert_eq!(schema.source["distinct_id"], "u2");

        let transform = &parsed.data[3];
        assert_eq!(transform.error.as_deref(), Some("No distinct_id found"));
        assert!(transform.outputs.is_empty());

        assert_eq!(parsed.data[4].outputs[0].event, "last");
    }

    #[test]
    fn partial_trailing_line_is_deferred_not_recorded_as_error() {
        let parser = captured_trial_parser();
        let complete = valid_line("first", "u1") + "\n";
        let chunk = format!("{complete}{{\"event\":\"spl");

        let parsed = parser(chunk.into_bytes()).unwrap();

        assert_eq!(
            parsed.data.len(),
            1,
            "the partial line must not produce a record"
        );
        assert_eq!(parsed.consumed, complete.len());
    }

    #[test]
    fn valid_unterminated_final_line_is_consumed() {
        let parser = captured_trial_parser();
        let chunk = valid_line("first", "u1") + "\n" + &valid_line("last", "u2");

        let parsed = parser(chunk.clone().into_bytes()).unwrap();

        assert_eq!(parsed.data.len(), 2);
        assert_eq!(parsed.consumed, chunk.len());
    }
}
