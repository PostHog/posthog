//! Split a stage batch into errored / empty / remote buckets.

use crate::error::UnhandledError;
use crate::stages::pipeline::ParsedPipelineItem;
use crate::types::{
    batch::Batch,
    exception_event::{ExceptionEvent, Parsed},
};

use super::RemoteEvent;

pub(super) struct Partition {
    pub(super) errors: Vec<(usize, ParsedPipelineItem)>,
    pub(super) empty: Vec<(usize, ParsedPipelineItem)>,
    pub(super) remote: Vec<RemoteEvent>,
}

pub(super) fn partition_batch(
    batch: Batch<ParsedPipelineItem>,
) -> Result<Partition, UnhandledError> {
    let mut errors = Vec::new();
    let mut empty = Vec::new();
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

        remote.push(prepare_remote_event(batch_index, evt)?);
    }

    Ok(Partition {
        errors,
        empty,
        remote,
    })
}

fn prepare_remote_event(
    batch_index: usize,
    mut evt: ExceptionEvent<Parsed>,
) -> Result<RemoteEvent, UnhandledError> {
    let exception_jsons: Vec<Vec<u8>> = evt
        .exception_list
        .iter()
        .map(|exc| serde_json::to_vec(exc).map_err(UnhandledError::from))
        .collect::<Result<_, _>>()?;
    let legacy_exception_jsons = evt
        .take_legacy_order_exception_list()
        .map(|exceptions| {
            exceptions
                .iter()
                .map(|exc| serde_json::to_vec(exc).map_err(UnhandledError::from))
                .collect::<Result<Vec<_>, _>>()
        })
        .transpose()?;
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
        legacy_exception_jsons,
        metadata,
    })
}
