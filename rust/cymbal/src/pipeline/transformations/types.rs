use std::{fmt::Display, str::FromStr};

use chrono::{DateTime, Utc};
use common_types::ClickHouseEvent;
use hogvm::VmError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::Postgres;
use uuid::Uuid;

pub struct TransformSetOutcome {
    pub results: Vec<TransformResult>,
    pub final_event: Option<ClickHouseEvent>,
}

pub struct TransformResult {
    pub function_id: Uuid,
    pub outcome: TransformOutcome,
    pub logs: Vec<TransformLog>,
}

pub struct TransformLog {
    pub message: String,
    pub level: String,
    pub timestamp: DateTime<Utc>,
}

pub enum TransformOutcome {
    Skipped,                   // The function filter skipped this event
    Success,                   // The transform was applied successfully
    FilterFailure(VmError),    // The transforms filter failed for some reason
    TransformFailure(VmError), // The transform function failed for some reason
}

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

#[derive(Debug, Clone, Copy)]
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
    pub encrypted_inputs: Option<String>, // Encrypted function inputs (Actually JSON, but stringified as part of encryption)
    pub filters: Option<Value>,           // Filter bytecode for the function
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

// All the globals that get injected into the hogvm runtime before execution
mod transform_globals {
    use std::collections::HashMap;

    use serde::{Deserialize, Serialize};
    use serde_json::Value;

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Project {
        pub id: i32,
        pub name: String,
        pub url: String,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Source {
        pub name: String,
        pub url: String,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Event {
        pub uuid: String,
        pub event: String,
        pub distinct_id: String,
        pub properties: HashMap<String, Value>,
        pub elements_chain: String,
        pub timestamp: String,
        pub url: String,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Person {
        pub id: String,
        pub properties: HashMap<String, Value>,
        pub name: String,
        pub url: String,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Group {
        pub id: String,     // The distinct_id equivalent, not the group type DB PK
        pub r#type: String, // Human readable group type
        pub index: i16,     // group index,
        pub url: String,
        pub properties: HashMap<String, Value>, // TODO - we probably won't support this for now
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Request {
        pub headers: HashMap<String, Option<String>>,
        pub ip: Option<String>,
        pub body: HashMap<String, Value>,
        pub string_body: String,
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransformInvocationGlobals {}

impl HogFunction {
    pub async fn fetch_for_team<'c, E>(
        e: E,
        team_id: i32,
        r#type: HogFunctionType,
    ) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            HogFunction,
            r#"
                SELECT
                    id,
                    team_id,
                    name,
                    description,
                    created_at,
                    created_by_id,
                    deleted,
                    updated_at,
                    enabled,
                    type,
                    kind,
                    icon_url,
                    hog,
                    bytecode,
                    transpiled,
                    inputs_schema,
                    inputs,
                    encrypted_inputs,
                    filters,
                    mappings,
                    masking,
                    template_id,
                    hog_function_template_id,
                    execution_order
                FROM posthog_hogfunction
                WHERE team_id = $1 AND deleted = false AND enabled = true AND type = $2
                ORDER BY execution_order, created_at ASC NULLS LAST -- in line with `sortHogFunctions` in plugin-server
            "#,
            team_id,
            r#type.to_string(),
        )
        .fetch_all(e)
        .await
    }
}

impl HogFunctionTemplate {
    pub async fn fetch_all<'c, E>(e: E) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            r#"
                SELECT
                    id,
                    template_id,
                    sha,
                    name,
                    description,
                    code,
                    code_language,
                    inputs_schema,
                    bytecode,
                    type,
                    status,
                    category,
                    kind,
                    free,
                    icon_url,
                    filters,
                    masking,
                    mapping_templates,
                    mappings,
                    created_at,
                    updated_at
                FROM posthog_hogfunctiontemplate
            "#,
        )
        .fetch_all(e)
        .await
    }

    pub async fn fetch_by_id<'c, E>(e: E, id: Uuid) -> Result<Self, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            r#"
                SELECT
                    id,
                    template_id,
                    sha,
                    name,
                    description,
                    code,
                    code_language,
                    inputs_schema,
                    bytecode,
                    type,
                    status,
                    category,
                    kind,
                    free,
                    icon_url,
                    filters,
                    masking,
                    mapping_templates,
                    mappings,
                    created_at,
                    updated_at
                FROM posthog_hogfunctiontemplate
                WHERE id = $1
            "#,
            id
        )
        .fetch_one(e)
        .await
    }
}

impl Display for HogFunctionType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            HogFunctionType::Destination => write!(f, "destination"),
            HogFunctionType::SiteDestination => write!(f, "site_destination"),
            HogFunctionType::InternalDestination => write!(f, "internal_destination"),
            HogFunctionType::SourceWebhook => write!(f, "source_webhook"),
            HogFunctionType::SiteApp => write!(f, "site_app"),
            HogFunctionType::Transformation => write!(f, "transformation"),
        }
    }
}

impl FromStr for HogFunctionType {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "destination" => Ok(HogFunctionType::Destination),
            "site_destination" => Ok(HogFunctionType::SiteDestination),
            "internal_destination" => Ok(HogFunctionType::InternalDestination),
            "source_webhook" => Ok(HogFunctionType::SourceWebhook),
            "site_app" => Ok(HogFunctionType::SiteApp),
            "transformation" => Ok(HogFunctionType::Transformation),
            _ => Err(()),
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
                .map(|s| s.len())
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
