//! The personally visible store catalog, installations and tool approval settings.
use super::{Gateway, Installation};
use crate::api::ProjectEndpoint;
use anyhow::{Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

/// Store template available for installation.
#[derive(Clone, Deserialize, Serialize)]
pub struct Template {
    /// Store identifier.
    pub id: Uuid,
    /// Vendor display name.
    pub name: String,
    /// Service endpoint.
    pub url: String,
    /// Store summary.
    pub description: String,
    /// Authentication method.
    pub auth_type: String,
    /// Store grouping, such as `business` or `dev`.
    #[serde(default)]
    pub category: Option<String>,
    /// Domain whose mark represents the vendor.
    #[serde(default)]
    pub icon_domain: Option<String>,
    /// Vendor documentation.
    #[serde(default)]
    pub docs_url: Option<String>,
}

/// Installation visible to the account, including pending OAuth connections.
#[derive(Clone, Deserialize, Serialize)]
pub struct Installed {
    /// Installation identifier.
    pub id: Uuid,
    /// Catalog origin, when present.
    pub template_id: Option<Uuid>,
    /// Display name.
    pub name: String,
    /// Upstream endpoint.
    pub url: String,
    /// Authentication method.
    pub auth_type: String,
    /// Whether the installation can be used.
    pub is_enabled: bool,
    /// Whether this user owns the credential.
    pub is_owner: bool,
    /// The provider requires renewed credentials.
    pub needs_reauth: bool,
    /// Initial OAuth authorization is incomplete.
    pub pending_oauth: bool,
    /// Active upstream tools.
    pub tool_count: usize,
}

/// States enforced by the PostHog store, in increasing order of restriction.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Policy {
    /// Allow calls without approval.
    Approved,
    /// Require approval before a call.
    NeedsApproval,
    /// Block all calls.
    DoNotUse,
}

/// One installed tool and its effective policy.
#[derive(Clone, Deserialize, Serialize)]
pub struct ToolPolicy {
    /// Stable upstream name.
    pub tool_name: String,
    /// Human-readable description.
    pub description: String,
    /// Effective state.
    pub approval_state: Policy,
    /// Team ceiling for user changes.
    pub team_state: Option<Policy>,
    /// Set by a higher authority.
    pub locked: bool,
}

/// Store operations accepted by the device-authenticated Meep server.
#[derive(Deserialize, Serialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum Operation {
    /// Load installations and catalog.
    Browse,
    /// Install a catalog entry with an optional API key.
    Template {
        /// Catalog identifier.
        id: Uuid,
        /// Upstream credential.
        api_key: Option<String>,
    },
    /// Create a personal installation.
    Custom {
        /// User-visible name.
        name: String,
        /// Upstream endpoint.
        url: String,
        /// Use OAuth discovery.
        oauth: bool,
        /// Optional bearer key.
        api_key: Option<String>,
    },
    /// Open a new browser grant for an existing installation.
    Authorize {
        /// Installation identifier.
        id: Uuid,
    },
    /// Delete an installation.
    Remove {
        /// Installation identifier.
        id: Uuid,
    },
    /// Read tools or ask PostHog to rediscover them.
    Tools {
        /// Installation identifier.
        id: Uuid,
        /// Rediscover upstream tools.
        refresh: bool,
    },
    /// Change one tool's approval policy.
    SetPolicy {
        /// Installation identifier.
        id: Uuid,
        /// Upstream name.
        name: String,
        /// Requested approval state.
        policy: Policy,
    },
}

/// Result of a store operation. Credentials never form part of the response.
#[derive(Deserialize, Serialize)]
pub enum Outcome {
    /// Live installation list and store catalog.
    Catalog(Vec<Installed>, Vec<Template>),
    /// Current tools for the installation.
    Tools(Vec<ToolPolicy>),
    /// User authorization is required.
    Browser(String),
    /// The mutation succeeded.
    Updated,
}

#[derive(Deserialize)]
struct Page<T> {
    results: Vec<T>,
    next: Option<String>,
}

/// Perform one operation under a server-owned project grant.
pub async fn execute(
    origin: &str,
    project: u64,
    token: &str,
    operation: Operation,
) -> Result<Outcome> {
    let gateway = Gateway::new(origin, project)?;
    let api = &gateway.api;
    let install = match operation {
        Operation::Browse => {
            // The store pages its catalogue like the installations; read every page.
            let endpoint = ProjectEndpoint::new(origin, project, "mcp_servers")?;
            let mut listing: Page<Template> = endpoint.get(token, "?limit=100").await?;
            let mut catalog = listing.results;
            let mut visited = std::collections::HashSet::new();
            while let Some(next) = listing.next {
                ensure!(
                    visited.insert(next.clone()),
                    "Repeated store pagination link"
                );
                listing = endpoint.get(token, &next).await?;
                catalog.extend(listing.results);
            }
            let mut page: Page<Installed> = api.get(token, "").await?;
            let mut servers = page.results;
            let mut seen = std::collections::HashSet::new();
            while let Some(next) = page.next {
                ensure!(seen.insert(next.clone()), "Repeated store pagination link");
                page = api.get(token, &next).await?;
                servers.extend(page.results);
            }
            return Ok(Outcome::Catalog(servers, catalog));
        }
        Operation::Template { id, api_key } => {
            gateway
                .install_personal_template(token, id, api_key.as_deref())
                .await?
        }
        Operation::Custom {
            name,
            url,
            oauth,
            api_key,
        } => {
            let mut body = json!({"name":name,"url":url,"auth_type":if oauth {"oauth"} else {"api_key"},"scope":"personal","install_source":"posthog-code"});
            if let Some(key) = api_key {
                body["api_key"] = json!(key);
            }
            api.post(token, "install_custom/", body).await?
        }
        Operation::Authorize { id } => {
            api.get(
                token,
                &format!("authorize/?installation_id={id}&install_source=posthog-code"),
            )
            .await?
        }
        Operation::Remove { id } => {
            api.request(
                token,
                reqwest::Method::DELETE,
                &format!("{id}/"),
                None,
                None,
            )
            .await?;
            return Ok(Outcome::Updated);
        }
        Operation::Tools { id, refresh } => {
            let tools: Page<ToolPolicy> = if refresh {
                api.post(token, &format!("{id}/tools/refresh/"), json!({}))
                    .await?
            } else {
                api.get(token, &format!("{id}/tools/")).await?
            };
            return Ok(Outcome::Tools(tools.results));
        }
        Operation::SetPolicy { id, name, policy } => {
            ensure!(
                !name.is_empty() && name != "." && name != ".." && !name.contains('/'),
                "Invalid tool name"
            );
            let url = api.child_url(&[&id.to_string(), "tools", &name, ""]);
            api.request(
                token,
                reqwest::Method::PATCH,
                url.as_str(),
                Some(json!({"approval_state":policy})),
                None,
            )
            .await?;
            return Ok(Outcome::Updated);
        }
    };
    match install {
        Installation::Installed { .. } => Ok(Outcome::Updated),
        Installation::Authorize { redirect_url } => {
            let url = url::Url::parse(&redirect_url)?;
            ensure!(
                url.scheme() == "https"
                    && url.has_host()
                    && url.username().is_empty()
                    && url.password().is_none(),
                "Invalid authorization URL"
            );
            Ok(Outcome::Browser(redirect_url))
        }
    }
}
