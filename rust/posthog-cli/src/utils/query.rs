use anyhow::Error;
use serde::{Deserialize, Serialize};
use serde_json::Value;

// TODO - we could formalise a lot of this and move it into posthog-rs, tbh

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryRequest {
    pub query: Query,
    pub refresh: QueryRefresh,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Query {
    HogQLQuery { query: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryRefresh {
    Blocking,
}

pub type HogQLQueryResult = Result<HogQLQueryResponse, HogQLQueryErrorResponse>;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryResponse {
    pub cache_key: Option<String>,
    pub cache_target_age: Option<String>,
    pub clickhouse: Option<String>, // Clickhouse query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub columns: Vec<String>, // Columns returned from the query
    pub error: Option<String>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub explain: Vec<String>,
    #[serde(default, rename = "hasMore", deserialize_with = "null_is_false")]
    pub has_more: bool,
    pub hogql: Option<String>, // HogQL query text
    #[serde(default, deserialize_with = "null_is_false")]
    pub is_cached: bool,
    pub last_refresh: Option<String>, // Last time the query was refreshed
    pub next_allowed_client_refresh_time: Option<String>, // Next time the client can refresh the query
    pub offset: Option<i64>,                              // Offset of the response rows
    pub limit: Option<i64>,                               // Limit of the query
    pub query: Option<String>,                            // Query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub types: Vec<(String, String)>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub results: Vec<Vec<Value>>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub timings: Vec<Timing>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryErrorResponse {
    pub code: String,
    pub detail: String,
    #[serde(rename = "type")]
    pub error_type: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Timing {
    pub k: String,
    pub t: f64,
}

fn null_is_empty<'de, D, T>(deserializer: D) -> Result<Vec<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: serde::Deserialize<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(Vec::new()),
    }
}

fn null_is_false<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(false),
    }
}

pub fn run_query(endpoint: &str, token: &str, to_run: &str) -> Result<HogQLQueryResult, Error> {
    let client = reqwest::blocking::Client::new();

    let request = QueryRequest {
        query: Query::HogQLQuery {
            query: to_run.to_string(),
        },
        refresh: QueryRefresh::Blocking,
    };

    let response = client
        .post(endpoint)
        .json(&request)
        .bearer_auth(token)
        .send()?;

    let code = response.status();
    let body = response.text()?;

    let value: Value = serde_json::from_str(&body)?;

    if !code.is_success() {
        let error: HogQLQueryErrorResponse = serde_json::from_value(value)?;
        return Ok(Err(error));
    }

    // NOTE: We don't do any pagination here, because the HogQLQuery runner doesn't support it
    let response: HogQLQueryResponse = serde_json::from_value(value)?;
    Ok(Ok(response))
}

impl std::error::Error for HogQLQueryErrorResponse {}

impl std::fmt::Display for HogQLQueryErrorResponse {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} ({}): {}", self.error_type, self.code, self.detail)
    }
}
