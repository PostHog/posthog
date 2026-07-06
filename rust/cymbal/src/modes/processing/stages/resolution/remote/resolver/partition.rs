//! Split a stage batch into errored / empty / local / remote buckets and
//! decide, per event, whether it samples into remote resolution.

use sha2::{Digest, Sha256};

use crate::error::UnhandledError;
use crate::metric_consts::REMOTE_RESOLUTION_SAMPLING;
use crate::stages::pipeline::ExceptionEventPipelineItem;
use crate::types::{batch::Batch, exception_properties::ExceptionProperties};

use super::RemoteEvent;

pub(super) struct Partition {
    pub(super) errors: Vec<(usize, ExceptionEventPipelineItem)>,
    pub(super) empty: Vec<(usize, ExceptionEventPipelineItem)>,
    pub(super) local: Vec<(usize, ExceptionProperties)>,
    pub(super) remote: Vec<RemoteEvent>,
}

pub(super) fn partition_batch(
    batch: Batch<ExceptionEventPipelineItem>,
    sample_rate: f64,
) -> Result<Partition, UnhandledError> {
    let mut errors = Vec::new();
    let mut empty = Vec::new();
    let mut local = Vec::new();
    let mut remote = Vec::new();

    for (batch_index, item) in batch.into_iter().enumerate() {
        let evt = match item {
            Ok(evt) => evt,
            Err(err) => {
                errors.push((batch_index, Err(err)));
                continue;
            }
        };

        if evt.exception_list.is_empty() {
            empty.push((batch_index, Ok(evt)));
            continue;
        }

        if should_route_event_to_remote(&evt, sample_rate) {
            metrics::counter!(REMOTE_RESOLUTION_SAMPLING, "decision" => "remote").increment(1);
            remote.push(prepare_remote_event(batch_index, evt)?);
        } else {
            metrics::counter!(REMOTE_RESOLUTION_SAMPLING, "decision" => "local").increment(1);
            local.push((batch_index, evt));
        }
    }

    Ok(Partition {
        errors,
        empty,
        local,
        remote,
    })
}

fn prepare_remote_event(
    batch_index: usize,
    evt: ExceptionProperties,
) -> Result<RemoteEvent, UnhandledError> {
    let exception_jsons: Vec<Vec<u8>> = evt
        .exception_list
        .iter()
        .map(|exc| serde_json::to_vec(exc).map_err(UnhandledError::from))
        .collect::<Result<_, _>>()?;
    let metadata = if evt.debug_images.is_empty() {
        Vec::new()
    } else {
        serde_json::to_vec(&serde_json::json!({
            "debug_images_json": evt.debug_images,
        }))
        .map_err(UnhandledError::from)?
    };
    Ok(RemoteEvent {
        batch_index,
        evt,
        exception_jsons,
        metadata,
    })
}

fn should_route_event_to_remote(evt: &ExceptionProperties, sample_rate: f64) -> bool {
    if sample_rate <= 0.0 {
        return false;
    }
    if sample_rate >= 1.0 {
        return true;
    }

    let mut hasher = Sha256::new();
    hasher.update(evt.team_id.to_be_bytes());
    hasher.update(evt.uuid.as_bytes());
    let digest = hasher.finalize();
    let bucket_bytes: [u8; 8] = digest[..8]
        .try_into()
        .expect("sha256 digest always contains at least 8 bytes");
    let bucket = u64::from_be_bytes(bucket_bytes) as f64 / ((u64::MAX as f64) + 1.0);
    bucket < sample_rate
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    #[test]
    fn sampling_decision_is_stable_for_same_team_and_event_uuid() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 123;
        evt.uuid = Uuid::from_u128(0x123456789abcdef);

        let first = should_route_event_to_remote(&evt, 0.37);
        for _ in 0..100 {
            assert_eq!(should_route_event_to_remote(&evt, 0.37), first);
        }
    }

    #[test]
    fn sampling_decision_respects_rate_boundaries() {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom"
            }]
        }))
        .expect("valid exception properties");
        evt.team_id = 123;
        evt.uuid = Uuid::from_u128(0x123456789abcdef);

        assert!(!should_route_event_to_remote(&evt, 0.0));
        assert!(should_route_event_to_remote(&evt, 1.0));
    }
}
