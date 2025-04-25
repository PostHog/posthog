use crate::{
    api::{
        errors::FlagDefinitionsError,
        flag_definition_types::FlagDefinitionsResponse,
        request_handler::{FlagsQueryParams, RequestContext},
        flag_definitions_request_handler::process_flags_definitions_request,
    },
    router,
};

use axum::{
    debug_handler,
    extract::{MatchedPath, Query, State},
    http::{HeaderMap, Method},
    Json,
};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use uuid::Uuid;

#[debug_handler]
pub async fn flag_definitions(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    Query(query_params): Query<FlagsQueryParams>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<FlagDefinitionsResponse>, FlagDefinitionsError> {
    let request_id = Uuid::new_v4();

    let context = RequestContext {
        request_id,
        state,
        ip,
        headers: headers.clone(),
        meta: query_params.clone(),
        body: Bytes::new(),
    };

    let response = process_flags_definitions_request(context).await?;

    // TODO: Implement the actual flag definitions logic
    Ok(Json(response))
}
