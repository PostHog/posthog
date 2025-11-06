use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use common_types::ProjectId;
use serde_json::Value;
use std::{collections::HashMap, net::IpAddr, sync::Arc};
use uuid::Uuid;

use crate::{
    api::types::FlagsQueryParams, cohorts::cohort_cache_manager::CohortCacheManager,
    flags::flag_models::FeatureFlagList, router,
};

pub struct RequestContext {
    /// Shared state holding services (DB, Redis, GeoIP, etc.)
    pub state: State<router::State>,

    /// Client IP
    pub ip: IpAddr,

    /// HTTP headers
    pub headers: HeaderMap,

    /// Query params (contains compression, library version, etc.)
    pub meta: FlagsQueryParams,

    /// Raw request body
    pub body: Bytes,

    /// Request ID
    pub request_id: Uuid,
}

/// Represents the various property overrides that can be passed around
/// (person, group, groups, and optional hash key).
#[derive(Debug, Clone)]
pub struct RequestPropertyOverrides {
    pub person_properties: Option<HashMap<String, Value>>,
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    pub groups: Option<HashMap<String, Value>>,
    pub hash_key: Option<String>,
}

/// Represents all context required for evaluating a set of feature flags.
pub struct FeatureFlagEvaluationContext {
    pub team_id: i32,
    pub project_id: ProjectId,
    pub distinct_id: String,
    pub feature_flags: FeatureFlagList,
    pub persons_reader: Arc<dyn common_database::Client + Send + Sync>,
    pub persons_writer: Arc<dyn common_database::Client + Send + Sync>,
    pub non_persons_reader: Arc<dyn common_database::Client + Send + Sync>,
    pub non_persons_writer: Arc<dyn common_database::Client + Send + Sync>,
    pub cohort_cache: Arc<CohortCacheManager>,
    pub person_property_overrides: Option<HashMap<String, Value>>,
    pub group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    pub groups: Option<HashMap<String, Value>>,
    pub hash_key_override: Option<String>,
    /// Contains explicitly requested flag keys and their dependencies. If empty, all flags will be evaluated.
    pub flag_keys: Option<Vec<String>>,
}
