//! `ApplyEventRestrictions` step: drop / DLQ / force-overflow by token config.

use common_event_restrictions::{
    EventContext, Pipeline, Restriction, RestrictionFilters, RestrictionManager, RestrictionScope,
    RestrictionType,
};
use common_pipelines::{Step, StepError, StepResult};
use metrics::counter;

use super::context::{PreprocessOutput, WithHeaders};
use super::metrics_consts::OVERFLOWING_MESSAGES;

/// Applies event restrictions in priority order DROP -> DLQ -> FORCE_OVERFLOW,
/// mirroring the Node.js `createApplyEventRestrictionsStep`
/// (`event-preprocessing/apply-event-restrictions.ts`).
///
/// POC scope: only the static env lists are wired (`DROP_EVENTS_BY_TOKEN_DISTINCT_ID`,
/// `SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID`,
/// `INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID`). Redis-backed dynamic config
/// is a stretch goal (see POC_NOTES §consumer). The shared
/// `common-event-restrictions` `RestrictionManager` supplies token/filter
/// matching so the semantics match capture and the Node manager.
pub struct ApplyEventRestrictions {
    manager: RestrictionManager,
    /// Force-overflow only redirects when the lane is in redirect mode.
    overflow_redirect: bool,
    /// Fallback `preserve_key` when person processing is skipped
    /// (`INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY`).
    preserve_partition_locality: bool,
}

impl ApplyEventRestrictions {
    /// Build directly from a manager. Mostly for tests (e.g. to inject a DLQ
    /// restriction, which has no static env list).
    pub fn from_manager(
        manager: RestrictionManager,
        overflow_redirect: bool,
        preserve_partition_locality: bool,
    ) -> Self {
        Self {
            manager,
            overflow_redirect,
            preserve_partition_locality,
        }
    }

    /// Build from the three static comma-separated env lists.
    pub fn from_static_lists(
        drop_events: &str,
        skip_persons: &str,
        force_overflow: &str,
        overflow_redirect: bool,
        preserve_partition_locality: bool,
    ) -> Self {
        let mut manager = RestrictionManager::new();
        add_static_entries(&mut manager, RestrictionType::DropEvent, drop_events);
        add_static_entries(
            &mut manager,
            RestrictionType::SkipPersonProcessing,
            skip_persons,
        );
        add_static_entries(&mut manager, RestrictionType::ForceOverflow, force_overflow);
        Self::from_manager(manager, overflow_redirect, preserve_partition_locality)
    }
}

/// Parse one comma-separated env list into the manager under `Pipeline::Analytics`.
fn add_static_entries(
    manager: &mut RestrictionManager,
    restriction_type: RestrictionType,
    list: &str,
) {
    for entry in list.split(',').filter(|s| !s.is_empty()) {
        let (token, scope) = parse_static_entry(entry);
        manager
            .restrictions
            .entry(Pipeline::Analytics)
            .or_default()
            .entry(token)
            .or_default()
            .push(Restriction {
                restriction_type,
                scope,
                args: None,
            });
    }
}

/// Entry formats mirror the Node `addStaticRestrictions`:
/// - `token` — applies to all events for the token
/// - `token:distinct_id` — legacy, filtered to that distinct_id (`parts[1]`)
/// - `token:distinct_id:value` — filtered to `value` (`parts[2]`)
fn parse_static_entry(entry: &str) -> (String, RestrictionScope) {
    if entry.contains(":distinct_id:") {
        let mut it = entry.split(':');
        let token = it.next().unwrap_or("");
        let _mid = it.next();
        let value = it.next().unwrap_or("");
        (token.to_string(), filtered_by_distinct_id(value))
    } else if entry.contains(':') {
        let mut it = entry.split(':');
        let token = it.next().unwrap_or("");
        let distinct_id = it.next().unwrap_or("");
        (token.to_string(), filtered_by_distinct_id(distinct_id))
    } else {
        (entry.to_string(), RestrictionScope::AllEvents)
    }
}

fn filtered_by_distinct_id(distinct_id: &str) -> RestrictionScope {
    let mut filters = RestrictionFilters::default();
    filters.distinct_ids.insert(distinct_id.to_string());
    RestrictionScope::Filtered(filters)
}

impl<Fx> Step<WithHeaders, Fx> for ApplyEventRestrictions {
    type Out = WithHeaders;
    type Outputs = PreprocessOutput;

    fn apply(
        &self,
        event: WithHeaders,
        _fx: &mut Fx,
    ) -> Result<StepResult<WithHeaders, PreprocessOutput>, StepError> {
        let headers = &event.headers;
        let Some(token) = headers.token.as_deref().filter(|t| !t.is_empty()) else {
            return Ok(StepResult::Continue(event));
        };

        let ctx = EventContext {
            distinct_id: headers.distinct_id.as_deref(),
            session_id: headers.session_id.as_deref(),
            event_name: headers.event.as_deref(),
            event_uuid: headers.uuid.as_deref(),
            now_ts: chrono::Utc::now().timestamp(),
        };

        let restrictions = self
            .manager
            .get_restrictions(token, &ctx, Pipeline::Analytics);
        if restrictions.is_empty() {
            return Ok(StepResult::Continue(event));
        }

        // Priority 1: Drop
        if restrictions.contains(RestrictionType::DropEvent) {
            return Ok(StepResult::drop("blocked_token"));
        }
        // Priority 2: DLQ
        if restrictions.contains(RestrictionType::RedirectToDlq) {
            return Ok(StepResult::dlq("restricted_to_dlq"));
        }
        // Priority 3: Force overflow (only in redirect mode)
        if self.overflow_redirect && restrictions.contains(RestrictionType::ForceOverflow) {
            counter!(OVERFLOWING_MESSAGES).increment(1);
            let should_process_person =
                !restrictions.contains(RestrictionType::SkipPersonProcessing);
            let preserve_key = if should_process_person {
                true
            } else {
                self.preserve_partition_locality
            };
            return Ok(StepResult::redirect(
                PreprocessOutput::Overflow,
                preserve_key,
            ));
        }

        Ok(StepResult::Continue(event))
    }

    fn name(&self) -> &'static str {
        "apply_event_restrictions"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preprocess::headers::EventHeaders;

    fn event(token: &str, distinct_id: &str) -> WithHeaders {
        WithHeaders {
            headers: EventHeaders {
                token: Some(token.to_string()),
                distinct_id: Some(distinct_id.to_string()),
                ..Default::default()
            },
        }
    }

    fn apply(
        step: &ApplyEventRestrictions,
        ev: WithHeaders,
    ) -> StepResult<WithHeaders, PreprocessOutput> {
        step.apply(ev, &mut ()).expect("no error")
    }

    #[test]
    fn drops_blocked_token() {
        let step = ApplyEventRestrictions::from_static_lists("phc_drop", "", "", true, false);
        assert!(matches!(
            apply(&step, event("phc_drop", "user")),
            StepResult::Drop {
                reason: "blocked_token"
            }
        ));
    }

    #[test]
    fn redirects_force_overflow_preserving_key_when_person_processed() {
        let step = ApplyEventRestrictions::from_static_lists("", "", "phc_of", true, false);
        match apply(&step, event("phc_of", "user")) {
            StepResult::Redirect {
                output: PreprocessOutput::Overflow,
                preserve_key,
            } => assert!(preserve_key, "person processed -> preserve key"),
            other => panic!("expected redirect, got {other:?}"),
        }
    }

    #[test]
    fn force_overflow_with_skip_person_uses_locality_flag() {
        // Same token force-overflowed and skip-person: preserve_key follows the
        // partition-locality flag.
        for locality in [false, true] {
            let step =
                ApplyEventRestrictions::from_static_lists("", "phc_of", "phc_of", true, locality);
            match apply(&step, event("phc_of", "user")) {
                StepResult::Redirect { preserve_key, .. } => {
                    assert_eq!(preserve_key, locality);
                }
                other => panic!("expected redirect, got {other:?}"),
            }
        }
    }

    #[test]
    fn drop_takes_priority_over_overflow() {
        let step = ApplyEventRestrictions::from_static_lists("phc_x", "", "phc_x", true, false);
        assert!(matches!(
            apply(&step, event("phc_x", "user")),
            StepResult::Drop { .. }
        ));
    }

    #[test]
    fn overflow_not_redirected_when_lane_not_in_redirect_mode() {
        let step = ApplyEventRestrictions::from_static_lists("", "", "phc_of", false, false);
        assert!(matches!(
            apply(&step, event("phc_of", "user")),
            StepResult::Continue(_)
        ));
    }

    #[test]
    fn filters_by_distinct_id() {
        let step =
            ApplyEventRestrictions::from_static_lists("phc_x:target-user", "", "", true, false);
        assert!(matches!(
            apply(&step, event("phc_x", "target-user")),
            StepResult::Drop { .. }
        ));
        assert!(matches!(
            apply(&step, event("phc_x", "other-user")),
            StepResult::Continue(_)
        ));
    }

    #[test]
    fn missing_token_continues() {
        let step = ApplyEventRestrictions::from_static_lists("phc_drop", "", "", true, false);
        let ev = WithHeaders {
            headers: EventHeaders::default(),
        };
        assert!(matches!(apply(&step, ev), StepResult::Continue(_)));
    }

    #[test]
    fn dlq_restriction_takes_priority_over_overflow() {
        // No static env list feeds DLQ; inject via the manager to prove priority.
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::Analytics,
            "phc_dlq",
            vec![
                Restriction {
                    restriction_type: RestrictionType::RedirectToDlq,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::AllEvents,
                    args: None,
                },
            ],
        );
        let step = ApplyEventRestrictions::from_manager(manager, true, false);
        assert!(matches!(
            apply(&step, event("phc_dlq", "user")),
            StepResult::Dlq {
                reason: "restricted_to_dlq",
                ..
            }
        ));
    }
}
