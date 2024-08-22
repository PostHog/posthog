use std::collections::HashMap;
use std::sync::Arc;

use axum::{debug_handler, Json};
use bytes::Bytes;
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use tracing::{error, instrument, warn};

use crate::api::FlagValue;
use crate::database::Client;
use crate::flag_definitions::FeatureFlagList;
use crate::flag_matching::FeatureFlagMatcher;
use crate::v0_request::Compression;
use crate::{
    api::{FlagError, FlagsResponse},
    router,
    v0_request::{FlagRequest, FlagsQueryParams},
};

/// Feature flag evaluation endpoint.
/// Only supports a specific shape of data, and rejects any malformed data.

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
pub async fn flags(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<FlagsResponse>, FlagError> {
    // TODO this could be extracted into some load_data_for_request type thing
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let comp = match meta.compression {
        None => String::from("unknown"),
        Some(Compression::Gzip) => String::from("gzip"),
        // Some(Compression::Base64) => String::from("base64"),
        Some(Compression::Unsupported) => String::from("unsupported"),
    };
    // TODO what do we use this for?
    let sent_at = meta.sent_at.unwrap_or(0);

    tracing::Span::current().record("user_agent", user_agent);
    tracing::Span::current().record("content_encoding", content_encoding);
    tracing::Span::current().record("version", meta.version.clone());
    tracing::Span::current().record("lib_version", meta.lib_version.clone());
    tracing::Span::current().record("compression", comp.as_str());
    tracing::Span::current().record("method", method.as_str());
    tracing::Span::current().record("path", path.as_str().trim_end_matches('/'));
    tracing::Span::current().record("ip", ip.to_string());
    tracing::Span::current().record("sent_at", &sent_at.to_string());

    tracing::debug!("request headers: {:?}", headers);

    // TODO handle different content types and encodings
    let request = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/json" => {
            tracing::Span::current().record("content_type", "application/json");
            FlagRequest::from_bytes(body)
        }
        // TODO support other content types
        ct => {
            return Err(FlagError::RequestDecodingError(format!(
                "unsupported content type: {}",
                ct
            )));
        }
    }?;

    // this errors up top-level if there's no token
    // return the team here, too?
    let token = request
        .extract_and_verify_token(state.redis.clone(), state.postgres.clone())
        .await?;

    // at this point, we should get the team since I need the team values for options on the payload
    // Note that the team here is different than the redis team.
    // TODO: consider making team an option, since we could fetch a project instead of a team
    // if the token is valid by the team doesn't exist for some reason.  Like, there might be a case
    // where the token exists in the database but the team has been deleted.
    // That said, though, I don't think this is necessary because we're already validating that the token exists
    // in the database, so if it doesn't exist, we should be returning an error there.
    // TODO make that one request; we already extract the token by accessing the team table, so we can just extract the team here
    let team = request
        .get_team_from_cache_or_pg(&token, state.redis.clone(), state.postgres.clone())
        .await?;

    // this errors up top-level if there's no distinct_id or missing one
    let distinct_id = request.extract_distinct_id()?;

    // TODO handle disabled flags, should probably do that right at the beginning

    tracing::Span::current().record("token", &token);
    tracing::Span::current().record("distinct_id", &distinct_id);

    tracing::debug!("request: {:?}", request);

    // now that I have a team ID and a distinct ID, I can evaluate the feature flags

    // first, get the flags
    let all_feature_flags = request
        .get_flags_from_cache_or_pg(team.id, state.redis.clone(), state.postgres.clone())
        .await?;

    tracing::Span::current().record("flags", &format!("{:?}", all_feature_flags));

    // debug log, I'm keeping it around bc it's useful
    // tracing::debug!(
    //     "flags: {}",
    //     serde_json::to_string_pretty(&all_feature_flags)
    //         .unwrap_or_else(|_| format!("{:?}", all_feature_flags))
    // );

    let flags_response =
        evaluate_feature_flags(distinct_id, all_feature_flags, Some(state.postgres.clone())).await;

    Ok(Json(flags_response))

    // TODO need to handle experience continuity here
}

pub async fn evaluate_feature_flags(
    distinct_id: String,
    feature_flag_list: FeatureFlagList,
    database_client: Option<Arc<dyn Client + Send + Sync>>,
) -> FlagsResponse {
    let mut matcher = FeatureFlagMatcher::new(distinct_id.clone(), database_client);
    let mut feature_flags = HashMap::new();
    let mut error_while_computing_flags = false;
    let all_feature_flags = feature_flag_list.flags;

    for flag in all_feature_flags {
        if !flag.active || flag.deleted {
            continue;
        }

        let flag_match = matcher.get_match(&flag).await;

        let flag_value = if flag_match.matches {
            match flag_match.variant {
                Some(variant) => FlagValue::String(variant),
                None => FlagValue::Boolean(true),
            }
        } else {
            FlagValue::Boolean(false)
        };

        feature_flags.insert(flag.key.clone(), flag_value);

        if let Err(e) = matcher
            .get_person_properties(flag.team_id, distinct_id.clone())
            .await
        {
            error_while_computing_flags = true;
            error!(
                "Error fetching properties for feature flag '{}' and distinct_id '{}': {:?}",
                flag.key, distinct_id, e
            );
        }
    }

    if error_while_computing_flags {
        warn!(
            "Errors occurred while computing feature flags for distinct_id '{}'",
            distinct_id
        );
    }

    FlagsResponse {
        error_while_computing_flags,
        feature_flags,
    }
}
