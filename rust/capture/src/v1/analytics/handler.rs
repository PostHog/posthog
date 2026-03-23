use axum::body::Body;
use axum::extract::{MatchedPath, Query as AxumQuery, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;

use super::query::Query;
use super::response::Response;
use crate::{router, v1};

pub async fn handle_request(
    _state: State<router::State>,
    _headers: HeaderMap,
    _query: AxumQuery<Query>,
    _ip: InsecureClientIp,
    _method: Method,
    _path: MatchedPath,
    _body: Body,
) -> Result<Response, v1::Error> {
    unimplemented!()
}
