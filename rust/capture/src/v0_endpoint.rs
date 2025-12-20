use axum::body::Body;
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use tracing::{error, instrument, warn, Span};

use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    events::{analytics::process_events, recordings::process_replay_events},
    payload::{handle_event_payload, handle_recording_payload, EventQuery},
    prometheus::{report_dropped_events, report_internal_error_metrics},
    router,
};

#[instrument(
    skip(state, body, meta),
    fields(params_lib_version, params_compression)
)]
#[debug_handler]
pub async fn event(
    state: State<router::State>,
    ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<CaptureResponse, CaptureError> {
    let mut params: EventQuery = meta.0;

    // TODO(eli): temporary peek at these
    if params.lib_version.is_some() {
        Span::current().record(
            "params_lib_version",
            format!("{:?}", params.lib_version.as_ref()),
        );
    }
    if params.compression.is_some() {
        Span::current().record(
            "params_compression",
            format!("{}", params.compression.unwrap()),
        );
    }

    match handle_event_payload(&state, &ip, &mut params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => {
            // Short term: return OK here to avoid clients retrying over and over
            // Long term: v1 endpoints will return richer errors, sync w/SDK behavior
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(CaptureError::EmptyPayloadFiltered) => {
            // as per legacy behavior, for now we'll silently accept these submissions
            // when invalid event type filtering has resulted in an empty event payload
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(err) => {
            report_internal_error_metrics(err.to_metric_tag(), "parsing");
            error!("event: request payload parsing error: {:?}", err);
            Err(err)
        }

        Ok((context, events)) => {
            if let Err(err) = process_events(
                state.sink.clone(),
                state.token_dropper.clone(),
                state.event_restriction_service.clone(),
                state.historical_cfg.clone(),
                &events,
                &context,
            )
            .await
            {
                report_dropped_events(err.to_metric_tag(), events.len() as u64);
                report_internal_error_metrics(err.to_metric_tag(), "processing");
                warn!("event: rejected payload: {}", err);
                return Err(err);
            }

            Ok(CaptureResponse {
                status: if params.beacon {
                    CaptureResponseCode::NoContent
                } else {
                    CaptureResponseCode::Ok
                },
                quota_limited: None,
            })
        }
    }
}

#[instrument(
    skip_all,
    fields(
        path,
        token,
        batch_size,
        user_agent,
        content_encoding,
        content_type,
        version,
        compression,
        historical_migration
    )
)]
#[debug_handler]
pub async fn recording(
    state: State<router::State>,
    ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<CaptureResponse, CaptureError> {
    let mut params: EventQuery = meta.0;

    match handle_recording_payload(&state, &ip, &mut params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => Ok(CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: Some(vec!["recordings".to_string()]),
        }),
        Err(err) => {
            report_internal_error_metrics(err.to_metric_tag(), "parsing");
            error!("recordings: request payload parsing error: {:?}", err);
            Err(err)
        }
        Ok((context, events)) => {
            let count = events.len() as u64;
            if let Err(err) = process_replay_events(state.sink.clone(), events, &context).await {
                report_dropped_events(err.to_metric_tag(), count);
                report_internal_error_metrics(err.to_metric_tag(), "processing");
                warn!("recordings:rejected payload: {:?}", err);
                return Err(err);
            }
            Ok(CaptureResponse {
                status: if params.beacon {
                    CaptureResponseCode::NoContent
                } else {
                    CaptureResponseCode::Ok
                },
                quota_limited: None,
            })
        }
    }
}

pub async fn options() -> Result<Json<CaptureResponse>, CaptureError> {
    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    }))
}
