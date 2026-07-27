use std::ops::{Deref, DerefMut};

use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;

use super::query::Query;
use super::types::Batch;
use crate::v1::context::RequestContext;
use crate::v1::Error;

/// Analytics-mode request context: the shared [`RequestContext`] plus the
/// typed analytics [`Query`] refined from `req.raw_query`. Derefs to
/// `RequestContext` so shared contracts (`Event`, `Sink`, logging) consume it
/// transparently.
pub struct Context {
    pub req: RequestContext,
    pub query: Query,
}

impl Context {
    pub fn new(
        headers: &HeaderMap,
        ip: &InsecureClientIp,
        raw_query: Option<String>,
        method: Method,
        path: &'static str,
    ) -> Result<Self, Error> {
        // Validate the request first, then refine the typed query from the raw
        // string. `Query` is currently empty so parsing never fails; the seam
        // is here for when analytics adds real query params.
        let req = RequestContext::new(headers, ip, raw_query, method, path)?;
        let query = match req.raw_query.as_deref() {
            Some(raw) => serde_urlencoded::from_str(raw)
                .map_err(|e| Error::InvalidQueryParam(format!("invalid query string: {e}")))?,
            None => Query::default(),
        };
        Ok(Self { req, query })
    }

    /// Stamp request-level batch metadata from the analytics batch envelope.
    pub fn set_batch_metadata(&mut self, batch: &Batch) {
        self.req.set_batch_metadata(
            Some(batch.created_at.clone()),
            batch.capture_internal.unwrap_or(false),
            batch.historical_migration,
        );
    }
}

impl Deref for Context {
    type Target = RequestContext;

    fn deref(&self) -> &RequestContext {
        &self.req
    }
}

impl DerefMut for Context {
    fn deref_mut(&mut self) -> &mut RequestContext {
        &mut self.req
    }
}
