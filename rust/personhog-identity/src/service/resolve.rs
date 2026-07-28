//! Eventual-consistency identity resolution for the hot per-event path: one
//! replica-pool probe returning identity columns only. Ingestion does not
//! need fresh properties at resolve time — the leader owns the property diff.

use tonic::Status;

use personhog_proto::personhog::identity::v1::ResolveDistinctIdResult;
use personhog_proto::personhog::types::v1::TeamDistinctId;

use crate::service::error::log_and_convert_error;
use crate::service::validation::{validate_batch_size, validate_key};
use crate::service::PersonHogIdentityService;

const RESOLVE_TOTAL: &str = "personhog_identity_resolve_total";

fn count_outcome(outcome: &'static str, count: usize) {
    if count > 0 {
        common_metrics::inc(
            RESOLVE_TOTAL,
            &[("outcome".to_string(), outcome.to_string())],
            count as u64,
        );
    }
}

impl PersonHogIdentityService {
    /// Resolves a batch of cross-team keys on the replica pool. Results are
    /// in key order; a key that maps to no person yields an absent identity.
    /// Malformed keys reject the whole request — the batch is a single probe,
    /// so there is no per-key failure mode to report.
    pub(crate) async fn resolve_keys(
        &self,
        keys: Vec<TeamDistinctId>,
    ) -> Result<Vec<ResolveDistinctIdResult>, Status> {
        validate_batch_size(&self.limits, keys.len())?;
        for key in &keys {
            validate_key(&self.limits, key)?;
        }

        let lookup: Vec<(i64, String)> = keys
            .iter()
            .map(|key| (key.team_id, key.distinct_id.clone()))
            .collect();
        let resolved = self
            .storage
            .resolve_identities(&lookup)
            .await
            .map_err(|e| log_and_convert_error(e, "resolve_identities"))?;

        let results: Vec<ResolveDistinctIdResult> = keys
            .into_iter()
            .map(|key| {
                let identity = resolved
                    .get(&(key.team_id, key.distinct_id.clone()))
                    .cloned()
                    .map(Into::into);
                ResolveDistinctIdResult {
                    team_id: key.team_id,
                    distinct_id: key.distinct_id,
                    identity,
                }
            })
            .collect();

        let found = results.iter().filter(|r| r.identity.is_some()).count();
        count_outcome("found", found);
        count_outcome("not_found", results.len() - found);

        Ok(results)
    }
}
