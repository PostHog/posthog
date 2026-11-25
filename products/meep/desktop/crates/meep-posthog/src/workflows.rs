//! Bind an existing PostHog workflow to a host capability. The origin, project,
//! flow ID and credentials are chosen by the host, outside the authored recipe.
use crate::api::ProjectEndpoint;
use anyhow::{Result, ensure};
use futures_util::{StreamExt, stream};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use uuid::Uuid;

/// A specific workflow in one PostHog project.
#[derive(Clone)]
pub struct BoundWorkflow {
    api: ProjectEndpoint,
    flow: Uuid,
}

/// The service's acknowledgement of a dispatch.
#[derive(Debug, Serialize, Deserialize)]
pub struct Receipt {
    /// ID to use for subsequent status queries.
    pub invocation_id: Uuid,
    /// Status reported at dispatch time.
    pub status: String,
}

/// A workflow dispatch may have reached PostHog without returning a receipt.
#[derive(Debug, thiserror::Error)]
#[error("PostHog may have started the workflow but did not return a readable receipt")]
pub struct DispatchUncertain;

/// An observation of a workflow invocation.
#[derive(Debug, Serialize, Deserialize)]
pub struct Invocation {
    /// PostHog invocation identifier.
    pub invocation_id: Uuid,
    /// Most recently observed execution status.
    pub status: String,
    /// Elapsed execution time, when available.
    pub duration_ms: Option<u64>,
}

#[derive(Deserialize)]
struct InvocationCount {
    count: usize,
}

/// Invocation history, including the observed timestamps and failure reason.
#[derive(Debug, Deserialize)]
pub struct InvocationDetails {
    /// The observed status and duration of the invocation.
    #[serde(flatten)]
    pub invocation: Invocation,
    /// When execution began, if the run has started.
    pub started_at: Option<chrono::DateTime<chrono::Utc>>,
    /// When the run was scheduled.
    pub scheduled_at: Option<chrono::DateTime<chrono::Utc>>,
    /// Error recorded for this invocation.
    pub error_message: Option<String>,
}

impl BoundWorkflow {
    /// Bind a client to a project's existing flow.
    pub fn new(origin: &str, project: u64, flow: Uuid) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::new(origin, project, "hog_flows")?,
            flow,
        })
    }

    /// Dispatch an active manual or schedule-triggered flow. Reuse the same key
    /// when retrying this logical dispatch, including after an ambiguous timeout.
    pub async fn start(
        &self,
        token: &str,
        key: Uuid,
        variables: &Map<String, Value>,
    ) -> Result<Receipt> {
        self.start_for(token, &self.flow.to_string(), key, variables)
            .await
    }

    /// Dispatch with the given host identity for compatibility with callers.
    /// PostHog runs manual workflows as the authenticated user.
    pub async fn start_for(
        &self,
        token: &str,
        _user_id: &str,
        key: Uuid,
        variables: &Map<String, Value>,
    ) -> Result<Receipt> {
        let variables: Map<_, _> = variables
            .iter()
            .filter(|(_, v)| !v.is_null())
            .map(|(k, v)| {
                let v = match v {
                    Value::Array(_) | Value::Object(_) => Value::String(v.to_string()),
                    value => value.clone(),
                };
                (k.clone(), v)
            })
            .collect();
        self.api
            .post_with_key(
                token,
                &format!("{}/run/", self.flow),
                json!({"variables":variables}),
                Some(&key.to_string()),
            )
            .await
            .map_err(|error| {
                if error
                    .downcast_ref::<reqwest::Error>()
                    .is_some_and(|e| !e.is_connect() && !e.is_builder())
                {
                    anyhow::Error::new(DispatchUncertain)
                } else {
                    error
                }
            })
    }

    /// Check whether the bound workflow can accept work.
    pub async fn check_active(&self, token: &str) -> Result<()> {
        let flow: Value = self.api.get(token, &format!("{}/", self.flow)).await?;
        let status = flow["status"].as_str().unwrap_or("unknown");
        ensure!(status == "active", "PostHog workflow status is {status}");
        ensure!(flow["enabled"] != false, "PostHog workflow is disabled");
        Ok(())
    }

    /// Read the status of an invocation of this flow.
    pub async fn status(&self, token: &str, invocation: Uuid) -> Result<Invocation> {
        self.api
            .get(
                token,
                &format!("{}/invocation_results/{invocation}/", self.flow),
            )
            .await
    }

    /// Find a unique invocation whose stored variables contain this observation.
    /// A full or incomplete page cannot establish uniqueness.
    pub async fn find_observation(
        &self,
        token: &str,
        observation: Uuid,
    ) -> Result<Option<Invocation>> {
        const LIMIT: u16 = 100;
        const CONCURRENCY: usize = 4;
        // The same absolute bound covers the original dispatch despite normal
        // clock skew or long downtime. Count around the list so a server that
        // silently truncates below its advertised limit cannot appear complete.
        let count_path = format!(
            "{}/invocation_results_count/?after=1970-01-01T00%3A00%3A00Z",
            self.flow
        );
        let before: InvocationCount = self.api.get(token, &count_path).await?;
        if before.count >= usize::from(LIMIT) {
            return Ok(None);
        }
        let recent: Vec<InvocationDetails> = self
            .api
            .get(
                token,
                &format!(
                    "{}/invocation_results/?limit={LIMIT}&after=1970-01-01T00%3A00%3A00Z",
                    self.flow
                ),
            )
            .await?;
        if recent.len() != before.count {
            return Ok(None);
        }
        let after: InvocationCount = self.api.get(token, &count_path).await?;
        if after.count != before.count {
            return Ok(None);
        }
        let unique: std::collections::HashSet<_> = recent
            .iter()
            .map(|entry| entry.invocation.invocation_id)
            .collect();
        if unique.len() != recent.len() {
            return Ok(None);
        }
        let mut found = None;
        let mut details = stream::iter(recent.into_iter().map(|entry| async move {
            let id = entry.invocation.invocation_id;
            let detail: Value = self
                .api
                .get(token, &format!("{}/invocation_results/{id}/", self.flow))
                .await?;
            Ok::<_, anyhow::Error>((id, detail))
        }))
        .buffer_unordered(CONCURRENCY);
        while let Some(result) = details.next().await {
            let (id, detail) = result?;
            ensure!(
                detail["invocation_id"]
                    .as_str()
                    .and_then(|v| v.parse::<Uuid>().ok())
                    == Some(id),
                "Invalid invocation detail"
            );
            let variables = detail
                .pointer("/invocation_globals/variables")
                .and_then(Value::as_object)
                .ok_or_else(|| anyhow::anyhow!("Invocation variables unavailable"))?;
            if variables
                .get("observation")
                .and_then(Value::as_str)
                .and_then(|v| v.parse::<Uuid>().ok())
                == Some(observation)
            {
                if found.is_some() {
                    return Ok(None);
                }
                found = Some(Invocation {
                    invocation_id: id,
                    status: detail["status"]
                        .as_str()
                        .ok_or_else(|| anyhow::anyhow!("Invocation status unavailable"))?
                        .to_owned(),
                    duration_ms: detail["duration_ms"].as_u64(),
                });
            }
        }
        if found.is_some() {
            // A stable count alone can hide an insertion/deletion swap. Require
            // the same complete identity set after reading every detail too.
            let verify: Vec<InvocationDetails> = self
                .api
                .get(
                    token,
                    &format!(
                        "{}/invocation_results/?limit={LIMIT}&after=1970-01-01T00%3A00%3A00Z",
                        self.flow
                    ),
                )
                .await?;
            let verified: std::collections::HashSet<_> = verify
                .iter()
                .map(|entry| entry.invocation.invocation_id)
                .collect();
            if verify.len() != before.count || verified != unique {
                return Ok(None);
            }
            let final_count: InvocationCount = self.api.get(token, &count_path).await?;
            if final_count.count != before.count {
                return Ok(None);
            }
        }
        Ok(found)
    }

    /// The most recent visible invocations, within PostHog's lookback window.
    pub async fn recent(&self, token: &str, limit: u16) -> Result<Vec<Invocation>> {
        Ok(self
            .recent_details(token, limit)
            .await?
            .into_iter()
            .map(|r| r.invocation)
            .collect())
    }

    /// Recent invocations including their scheduled or actual start time.
    pub async fn recent_details(&self, token: &str, limit: u16) -> Result<Vec<InvocationDetails>> {
        ensure!(
            (1..=500).contains(&limit),
            "Request between 1 and 500 recent runs"
        );
        self.api
            .get(
                token,
                &format!("{}/invocation_results/?limit={limit}", self.flow),
            )
            .await
    }
}
