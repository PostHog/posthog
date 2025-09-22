use std::{collections::HashMap, fmt::Debug, time::Duration};

use chrono::{DateTime, Utc};
use moka::sync::{Cache, CacheBuilder};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

use crate::error::UnhandledError;

// This entire module could be in `common`, and only isn't because nobody else needs it yet.

// These are returned by the CDP api, rather than persisted in PG, for some reason. We have to hit the API to fetch the function
// state, or else go to redis to get it ourselves.
pub enum HogFunctionState {
    Unknown,
    Healthy,
    Degraded,
    Disabled,
    ForcefullyDegraded,
    ForcefullyDisabled,
}

pub enum HogFunctionType {
    Destination,
    SiteDestination,
    InternalDestination,
    SourceWebhook,
    SiteApp,
    Transformation,
}

#[derive(Debug, Clone, Deserialize)]
pub struct HogFunctionFilter {
    pub bytecode: Option<Vec<Value>>,
}

#[derive(Debug, Clone)]
pub struct HogFunction {
    pub id: Uuid,
    pub team_id: i32,
    pub name: Option<String>,
    pub description: String,
    pub created_at: DateTime<Utc>,
    pub created_by_id: Option<i32>,
    pub deleted: bool,
    pub updated_at: DateTime<Utc>,
    pub enabled: bool,
    pub r#type: Option<String>, // Actually HogFunctionType, but stringified
    pub kind: Option<String>,   // Unused
    pub icon_url: Option<String>,
    pub hog: String,             // Source code of function, either typescript or hog
    pub bytecode: Option<Value>, // Hog bytecode
    pub transpiled: Option<String>, // If it's a site app or site destination, this is the javascript code
    pub inputs_schema: Option<Value>,
    pub inputs: Option<Value>,                  // Fixed function inputs
    pub encrypted_inputs: Option<Value>,        // Encrypted function inputs
    pub filters: Option<Value>,                 // Filter bytecode for the function
    pub mappings: Option<Value>, // Input mappings ?? TODO - figure out how these are used for transforms
    pub masking: Option<Value>, // Input masking ?? TODO - figure out how these are used for transforms
    pub template_id: Option<String>, // The id of the template this function is based on
    pub hog_function_template_id: Option<Uuid>, // The ID of the specific template version for this function
    pub execution_order: Option<i16>,
}

#[derive(Debug, Clone)]
pub struct HogFunctionTemplate {
    pub id: Uuid,
    pub template_id: String,
    pub sha: String,
    pub name: String,
    pub description: Option<String>,
    pub code: String,
    pub code_language: String, // "hog" or "javascript"
    pub inputs_schema: Value,
    pub bytecode: Option<Value>,
    pub r#type: String,
    pub status: String,
    pub category: Value,
    pub kind: Option<String>, // Deprecated
    pub free: bool,
    pub icon_url: Option<String>,
    pub filters: Option<Value>,
    pub masking: Option<Value>,
    pub mapping_templates: Option<Value>,
    pub mappings: Option<Value>, // Deprecated
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

pub struct HogFunctionManager {
    function_cache: Cache<i32, Vec<CachedWeight<HogFunction>>>,
    template_cache: Cache<Uuid, CachedWeight<HogFunctionTemplate>>,
}

#[derive(Debug, Clone, Default)]
pub struct HogFunctionManagerConfig {
    pub function_cache_size: u64,
    pub function_cache_ttl: Duration,
    pub template_cache_size: u64,
    pub template_cache_ttl: Duration,
}

impl HogFunctionManager {
    pub fn new(config: HogFunctionManagerConfig) -> Self {
        let function_cache = CacheBuilder::new(config.function_cache_size)
            .time_to_live(config.function_cache_ttl)
            .weigher(|_, v: &Vec<CachedWeight<HogFunction>>| {
                v.iter().map(|f| f.weight as u32).sum() // CAST: if this is larger than 4GB worth of data, we're dead anyway
            })
            .build();
        let template_cache = CacheBuilder::new(config.template_cache_size)
            .time_to_live(config.template_cache_ttl)
            .weigher(|_, v: &CachedWeight<HogFunctionTemplate>| v.weight as u32) // CAST: as above
            .build();
        HogFunctionManager {
            function_cache,
            template_cache,
        }
    }

    pub async fn get_functions(&self, team_id: i32) -> Result<Vec<HogFunction>, UnhandledError> {
        Ok(Vec::new())
    }

    pub async fn get_function_bytecode(
        &self,
        function: &HogFunction,
    ) -> Result<Option<Value>, UnhandledError> {
        Ok(None)
    }

    pub async fn get_function_globals(
        &self,
        function: &HogFunction,
    ) -> Result<Value, UnhandledError> {
        Ok(Value::Null)
    }

    pub async fn disable_function(
        &self,
        function: &HogFunction,
        s: impl ToString,
    ) -> Result<(), UnhandledError> {
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct CachedWeight<T>
where
    T: Clone + Debug,
{
    pub inner: T,
    pub weight: usize,
}

impl CachedWeight<HogFunction> {
    pub fn new(function: HogFunction) -> Self {
        let weight = function.cache_weight();
        CachedWeight {
            inner: function,
            weight,
        }
    }
}

impl CachedWeight<HogFunctionTemplate> {
    pub fn new(template: HogFunctionTemplate) -> Self {
        let weight = template.cache_weight();
        CachedWeight {
            inner: template,
            weight,
        }
    }
}

impl HogFunction {
    // Estimates the size in bytes of this function. Only includes non-fixed-size data (so nums, uuid's etc are excluded)
    pub fn cache_weight(&self) -> usize {
        // Rust introspection wen
        1 + self.name.as_ref().map(|s| s.len()).unwrap_or_default()
            + self.description.len()
            + self.r#type.as_ref().map(|s| s.len()).unwrap_or_default()
            + self.kind.as_ref().map(|s| s.len()).unwrap_or_default()
            + self.icon_url.as_ref().map(|s| s.len()).unwrap_or_default()
            + self.hog.len()
            + self
                .bytecode
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .transpiled
                .as_ref()
                .map(|s| s.len())
                .unwrap_or_default()
            + self
                .inputs_schema
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .inputs
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .encrypted_inputs
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .filters
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .mappings
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .masking
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .template_id
                .as_ref()
                .map(|s| s.len())
                .unwrap_or_default()
    }
}

impl HogFunctionTemplate {
    pub fn cache_weight(&self) -> usize {
        1 + self.template_id.len()
            + self.sha.len()
            + self.name.len()
            + self
                .description
                .as_ref()
                .map(|s| s.len())
                .unwrap_or_default()
            + self.code.len()
            + self.code_language.len()
            + estimate_value_size(&self.inputs_schema)
            + self
                .bytecode
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self.r#type.len()
            + self.status.len()
            + estimate_value_size(&self.category)
            + self.kind.as_ref().map(|s| s.len()).unwrap_or_default()
            + self.icon_url.as_ref().map(|s| s.len()).unwrap_or_default()
            + self
                .filters
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .masking
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .mapping_templates
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
            + self
                .mappings
                .as_ref()
                .map(estimate_value_size)
                .unwrap_or_default()
    }
}

// In-memory estimated resident size of a json value, excluding pointers
pub fn estimate_value_size(value: &Value) -> usize {
    match value {
        Value::Null => 0,
        Value::Bool(_) => 1,
        Value::Number(_) => 64 / 8, // Numbers are always 64 bits (i64, u64 or f64)
        Value::String(s) => s.len(), // Size of the string, plus a pointer, len and capacity
        Value::Array(arr) => arr.iter().map(estimate_value_size).sum(), // Size of the inners, plus a pointer, len and capacity
        Value::Object(obj) => obj
            .iter()
            .map(|(k, v)| k.len() + estimate_value_size(v))
            .sum(),
    }
}
