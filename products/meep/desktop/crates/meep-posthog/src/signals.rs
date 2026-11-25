//! PostHog Scout reports (the signals inbox): read ready reports and their
//! evidence, and write a person's verdict back.
use crate::api::ProjectEndpoint;
use anyhow::Result;
use serde::Deserialize;
use serde_json::{Value, json};

/// One Scout report as the list endpoint returns it.
#[derive(Clone, Debug, Deserialize)]
pub struct ScoutReport {
    /// Report UUID.
    pub id: String,
    /// Headline, possibly with a conventional-commit prefix.
    #[serde(default)]
    pub title: Option<String>,
    /// Markdown write-up; its first paragraph is the lead.
    #[serde(default)]
    pub summary: Option<String>,
    /// `ready`, `pending_input`, `resolved`, `suppressed`, …
    #[serde(default)]
    pub status: String,
    /// `P0`..`P4`, when judged.
    #[serde(default)]
    pub priority: Option<String>,
    /// Up to six measured numbers; the first affected-users or primary one is the impact.
    #[serde(default)]
    pub metrics: Vec<Value>,
    /// Prompts the scout suggests for the next step; the first stands in for a proposal.
    #[serde(default)]
    pub suggested_prompts: Vec<String>,
}

/// One piece of evidence behind a report.
#[derive(Clone, Debug, Deserialize)]
pub struct ScoutSignal {
    /// Producing product, such as `error_tracking` or `session_replay`.
    #[serde(default)]
    pub source_product: String,
    /// The object's identity in that product.
    #[serde(default)]
    pub source_id: String,
    /// Short description, when the producer wrote one.
    #[serde(default)]
    pub headline: Option<String>,
    /// Full description.
    #[serde(default)]
    pub content: String,
    /// When it happened.
    #[serde(default)]
    pub timestamp: Option<String>,
    /// Where to open it.
    #[serde(default)]
    pub link: Option<Value>,
}

#[derive(Deserialize)]
struct Page<T> {
    results: Vec<T>,
}

/// Project-scoped client for Scout reports.
#[derive(Clone)]
pub struct Signals {
    api: ProjectEndpoint,
}

impl Signals {
    /// Open the signals collection for a numeric project.
    pub fn new(origin: &str, project: u64) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::new(origin, project, "signals")?,
        })
    }

    /// Reports ready to act on, newest first, optionally matching a search.
    pub async fn ready_reports(
        &self,
        token: &str,
        search: Option<&str>,
        limit: usize,
    ) -> Result<Vec<ScoutReport>> {
        let mut path =
            format!("reports/?status=ready,pending_input&ordering=-updated_at&limit={limit}");
        if let Some(term) = search.map(str::trim).filter(|t| !t.is_empty()) {
            path.push_str("&search=");
            path.push_str(
                &url::form_urlencoded::byte_serialize(term.as_bytes()).collect::<String>(),
            );
        }
        Ok(self
            .api
            .get::<Page<ScoutReport>>(token, &path)
            .await?
            .results)
    }

    /// The evidence behind one report.
    pub async fn signals(&self, token: &str, report: &str) -> Result<Vec<ScoutSignal>> {
        let value: Value = self
            .api
            .get(token, &format!("reports/{report}/signals/"))
            .await?;
        // The endpoint answers with a page or a bare list depending on version.
        let list = value
            .get("signals")
            .or_else(|| value.get("results"))
            .cloned()
            .unwrap_or(value);
        Ok(serde_json::from_value(list).unwrap_or_default())
    }

    /// Close a report in PostHog: resolved, or dismissed (`suppressed`), with a reason.
    pub async fn set_state(
        &self,
        token: &str,
        report: &str,
        resolved: bool,
        reason: &str,
    ) -> Result<()> {
        let body = json!({
            "state": if resolved { "resolved" } else { "suppressed" },
            "dismissal_reason": reason,
        });
        let _: Value = self
            .api
            .post(token, &format!("reports/{report}/state/"), body)
            .await?;
        Ok(())
    }
}
