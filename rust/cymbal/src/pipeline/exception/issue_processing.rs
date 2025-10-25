use std::{
    collections::{hash_map::Entry, HashMap},
    sync::Arc,
};

use chrono::Utc;
use common_types::format::parse_datetime_assuming_utc;
use tracing::warn;

use crate::{
    app_context::AppContext,
    error::{PipelineResult, UnhandledError},
    issue_resolution::{resolve_issue, Issue},
    types::FingerprintedErrProps,
};

pub async fn do_issue_processing(
    context: Arc<AppContext>,
    events: &[PipelineResult],
    indexed_fingerprinted: &[(usize, FingerprintedErrProps)],
) -> Result<HashMap<String, Issue>, (usize, UnhandledError)> {
    let mut issue_handles = HashMap::new();
    for (index, fingerprinted) in indexed_fingerprinted.iter() {
        let to_resolve = fingerprinted.fingerprint.value.clone();
        let event = events[*index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering");

        let team_id = event.team_id;

        if let Entry::Vacant(e) = issue_handles.entry(to_resolve.clone()) {
            let name = fingerprinted
                .proposed_issue_name
                .clone()
                .unwrap_or(fingerprinted.exception_list[0].exception_type.clone());

            let description = fingerprinted
                .proposed_issue_description
                .clone()
                .unwrap_or(fingerprinted.exception_list[0].exception_message.clone());

            let event_timestamp =
                parse_datetime_assuming_utc(&event.timestamp).unwrap_or_else(|e| {
                    warn!(
                        event = event.uuid.to_string(),
                        "Failed to get event timestamp, using current time, error: {:?}", e
                    );
                    Utc::now()
                });

            let m_context = context.clone();
            let m_props = fingerprinted.clone();
            let handle = tokio::spawn(async move {
                resolve_issue(
                    m_context,
                    team_id,
                    name,
                    description,
                    event_timestamp,
                    m_props,
                )
                .await
            });
            e.insert(handle);
        }
    }

    let mut resolved_issues = HashMap::new();
    for (fingerprint, handle) in issue_handles.into_iter() {
        let issue = match handle.await.expect("issue resolution task did not panic") {
            Ok(i) => i,
            Err(e) => {
                let index =
                    find_index_with_matching_fingerprint(&fingerprint, indexed_fingerprinted);
                return Err((index, e));
            }
        };
        resolved_issues.insert(fingerprint, issue);
    }

    Ok(resolved_issues)
}

fn find_index_with_matching_fingerprint(
    fingerprint: &str,
    list: &[(usize, FingerprintedErrProps)],
) -> usize {
    for (index, props) in list.iter() {
        if props.fingerprint.value == fingerprint {
            return *index;
        }
    }
    0
}
