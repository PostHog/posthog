use std::sync::Arc;

use serde::Serialize;
use tiktoken_rs::cl100k_base;
use tracing::warn;

use crate::config::Config;
use crate::issue_resolution::Issue;
use crate::types::OutputErrProps;

/// Signal payload matching the Django internal API contract.
#[derive(Serialize)]
pub struct EmitSignalRequest {
    pub source_product: &'static str,
    pub source_type: &'static str,
    pub source_id: String,
    pub description: String,
    pub weight: f64,
    pub extra: serde_json::Value,
}

/// Context for building a signal from an issue + its error properties.
pub struct IssueSignalContext<'a> {
    pub issue: &'a Issue,
    pub props: &'a OutputErrProps,
    pub source_type: &'static str,
    /// Brief LLM-facing explanation of what this signal means, e.g. "New issue" or "Issue reopened".
    pub preamble: String,
    pub weight: f64,
    pub extra: serde_json::Value,
}

impl<'a> From<IssueSignalContext<'a>> for EmitSignalRequest {
    fn from(ctx: IssueSignalContext<'a>) -> Self {
        let header = format!(
            "{}:\n{}: {}\n",
            ctx.preamble,
            ctx.issue.name.as_deref().unwrap_or("Unknown"),
            ctx.issue.description.as_deref().unwrap_or(""),
        );
        let header_tokens = cl100k_base()
            .map(|bpe| bpe.encode_with_special_tokens(&header).len())
            .unwrap_or(0);
        let stacktrace = ctx.props.print_stacktrace(Some(8000 - header_tokens));
        let description = format!("{header}\n```\n{stacktrace}\n```");

        EmitSignalRequest {
            source_product: "error_tracking",
            source_type: ctx.source_type,
            source_id: ctx.issue.id.to_string(),
            description,
            weight: ctx.weight,
            extra: ctx.extra,
        }
    }
}

/// Thin HTTP client that emits signals via the internal Django API.
#[derive(Clone)]
pub struct SignalClient {
    // Notably, this client needs to allow hitting internal APIs, so is unsafe to use elsewhere.
    http: reqwest::Client,
    /// e.g. "http://posthog-web:8000"
    base_url: String,
    secret: String,
}

impl SignalClient {
    pub fn new(config: &Config) -> Self {
        Self {
            http: reqwest::Client::new(),
            base_url: config.signals_api_base_url.clone(),
            secret: config.internal_api_secret.clone(),
        }
    }

    pub async fn emit_issue_created(&self, issue: &Issue, props: &OutputErrProps) {
        let request = EmitSignalRequest::from(IssueSignalContext {
            issue,
            props,
            source_type: "issue_created",
            preamble: "New error tracking issue created - this particular exception was observed for the first time".to_string(),
            weight: 1.0,
            extra: serde_json::json!({
                "fingerprint": props.fingerprint,
            }),
        });
        self.send(issue.team_id, request).await;
    }

    pub async fn emit_issue_reopened(&self, issue: &Issue, props: &OutputErrProps) {
        let request = EmitSignalRequest::from(IssueSignalContext {
            issue,
            props,
            source_type: "issue_reopened",
            preamble: "Previously resolved error tracking issue has reappeared - this particular exception was observed previously, and thought to be resolved, but has reappeared".to_string(),
            weight: 1.0,
            extra: serde_json::json!({
                "fingerprint": props.fingerprint,
            }),
        });
        self.send(issue.team_id, request).await;
    }

    pub async fn emit_issue_spiking(
        &self,
        issue: &Issue,
        props: &OutputErrProps,
        computed_baseline: f64,
        current_bucket_value: f64,
    ) {
        let multiplier = current_bucket_value / computed_baseline;
        let preamble = format!(
            "This error tracking issue is experiencing a spike in occurrences
            (baseline: {computed_baseline:.1}, current: {current_bucket_value:.1}) ({multiplier:.1} over baseline)"
        );
        let request = EmitSignalRequest::from(IssueSignalContext {
            issue,
            props,
            source_type: "issue_spiking",
            preamble,
            weight: 1.0,
            extra: serde_json::json!({
                "fingerprint": props.fingerprint,
            }),
        });
        self.send(issue.team_id, request).await;
    }

    async fn send(&self, team_id: i32, body: EmitSignalRequest) {
        let url = format!(
            "{}/api/projects/{}/internal/signals/emit",
            self.base_url, team_id
        );
        match self
            .http
            .post(&url)
            .header("X-Internal-Api-Secret", &self.secret)
            .json(&body)
            .send()
            .await
        {
            Ok(resp) if !resp.status().is_success() => {
                warn!("Signal emit returned status {}", resp.status());
            }
            Err(e) => {
                warn!("Failed to emit signal: {e}");
            }
            _ => {}
        }
    }
}

/// Wraps an optional SignalClient. When signals are disabled, all calls are no-ops.
#[derive(Clone)]
pub struct MaybeSignalClient(Option<Arc<SignalClient>>);

impl MaybeSignalClient {
    pub fn disabled() -> Self {
        Self(None)
    }

    pub fn enabled(client: SignalClient) -> Self {
        Self(Some(Arc::new(client)))
    }

    pub fn emit_issue_created(&self, issue: &Issue, props: &OutputErrProps) {
        if let Some(c) = self.0.clone() {
            let issue = issue.clone();
            let props = props.clone();
            tokio::spawn(async move {
                c.emit_issue_created(&issue, &props).await;
            });
        }
    }

    pub fn emit_issue_reopened(&self, issue: &Issue, props: &OutputErrProps) {
        if let Some(c) = self.0.clone() {
            let issue = issue.clone();
            let props = props.clone();
            tokio::spawn(async move {
                c.emit_issue_reopened(&issue, &props).await;
            });
        }
    }

    pub fn emit_issue_spiking(
        &self,
        issue: &Issue,
        props: &OutputErrProps,
        computed_baseline: f64,
        current_bucket_value: f64,
    ) {
        if let Some(c) = self.0.clone() {
            let issue = issue.clone();
            let props = props.clone();
            tokio::spawn(async move {
                c.emit_issue_spiking(&issue, &props, computed_baseline, current_bucket_value)
                    .await;
            });
        }
    }
}
