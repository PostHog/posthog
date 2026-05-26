//! Routing-key extraction for Cymbal stage inputs.
//!
//! The resolution stage is the most affinity-sensitive: hitting the same pod
//! for the same symbol set or release source dramatically improves cache hit
//! rates. This module owns the priority order
//! (debug image > sourcemap symbol set > release/source > team id) and the
//! helpers that walk the (mostly free-form) event properties to find the
//! highest-cardinality cache key available.

use cymbal_core::routing::RoutingKey;
use cymbal_domain::InputEvent;
use serde_json::{Map, Value};

pub(crate) fn resolution_routing_key(event: &InputEvent) -> RoutingKey {
    if let Some(debug_image_id) = first_debug_image_id(&event.properties.debug_images) {
        return RoutingKey::debug_image_id(event.team_id, debug_image_id);
    }

    if let Some(symbol_set_ref) = first_symbol_set_ref(event) {
        return RoutingKey::symbol_set_ref(event.team_id, symbol_set_ref);
    }

    if let Some(release_source) = first_release_source_ref(event) {
        return RoutingKey::release_source(event.team_id, release_source);
    }

    RoutingKey::team_id(event.team_id)
}

fn first_debug_image_id(debug_images: &[Value]) -> Option<String> {
    debug_images.iter().find_map(|image| {
        let image = image.as_object()?;
        first_non_empty_string_field(image, &["debug_id", "debugId", "image_uuid", "uuid"])
    })
}

fn first_symbol_set_ref(event: &InputEvent) -> Option<String> {
    event.properties.exception_list.as_ref().and_then(|list| {
        list.0.iter().find_map(|exception| {
            exception.stacktrace.as_ref().and_then(|stacktrace| {
                stacktrace.frames.iter().find_map(|frame| {
                    first_non_empty_string_field(
                        &frame.other,
                        &[
                            "chunk_id",
                            "chunkId",
                            "sourcemap_id",
                            "sourcemapId",
                            "source_map_id",
                            "sourceMapId",
                        ],
                    )
                })
            })
        })
    })
}

fn first_release_source_ref(event: &InputEvent) -> Option<String> {
    if let Some(source) = first_exception_source(event) {
        if let Some(release) = first_release_value(&event.properties.exception_releases) {
            return Some(format!("release:{release}:source:{source}"));
        }
        return Some(format!("source:{source}"));
    }

    first_release_value(&event.properties.exception_releases)
        .map(|release| format!("release:{release}"))
}

fn first_exception_source(event: &InputEvent) -> Option<String> {
    event.properties.exception_list.as_ref().and_then(|list| {
        list.0.iter().find_map(|exception| {
            exception.stacktrace.as_ref().and_then(|stacktrace| {
                stacktrace.frames.iter().find_map(|frame| {
                    frame
                        .source
                        .as_deref()
                        .or(frame.filename.as_deref())
                        .and_then(non_empty_string)
                        .map(ToString::to_string)
                })
            })
        })
    })
}

fn first_release_value(releases: &Map<String, Value>) -> Option<String> {
    releases.iter().find_map(|(key, value)| {
        value
            .as_str()
            .and_then(non_empty_string)
            .map(ToString::to_string)
            .or_else(|| non_empty_string(key).map(ToString::to_string))
    })
}

fn first_non_empty_string_field(object: &Map<String, Value>, fields: &[&str]) -> Option<String> {
    fields.iter().find_map(|field| {
        object
            .get(*field)
            .and_then(Value::as_str)
            .and_then(non_empty_string)
            .map(ToString::to_string)
    })
}

fn non_empty_string(value: &str) -> Option<&str> {
    if value.is_empty() {
        return None;
    }

    Some(value)
}
