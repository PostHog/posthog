//! Clients for PostHog's native MCP server and its connected-installation gateway.
mod session;
pub use session::{DEFAULT_ENDPOINT, McpClient, McpSession, McpTool};

use crate::api::ProjectEndpoint;
use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use uuid::Uuid;

/// An installed MCP server visible to the authenticated account.
#[derive(Debug, Deserialize, Serialize)]
pub struct Server {
    /// Identifier used to address calls to this installation.
    pub installation_id: Uuid,
    /// Display name of the installation.
    pub name: String,
    /// Short service name returned by the gateway.
    pub slug: String,
    /// Tools advertised by this installation.
    pub tools: Vec<Tool>,
}

/// A tool exposed through an installed MCP server.
#[derive(Debug, Deserialize, Serialize)]
pub struct Tool {
    /// Upstream name used when calling the tool.
    pub name: String,
    /// Description supplied by the server.
    pub description: String,
    /// JSON Schema for the tool arguments.
    pub input_schema: Value,
    /// MCP annotations supplied by the server.
    pub annotations: Value,
    /// Approval state for this user's installation.
    pub approval_state: String,
}

/// The content and error indicator returned by an MCP tool.
#[derive(Debug, Deserialize, Serialize)]
pub struct ToolResult {
    /// Protocol content blocks, which may contain text, JSON text, or media.
    pub content: Vec<Value>,
    /// Whether the upstream tool rejected the call.
    #[serde(default, alias = "isError")]
    pub is_error: bool,
    /// Machine-readable result when the tool supplies one.
    #[serde(alias = "structuredContent")]
    pub structured_content: Option<Value>,
}

/// An OAuth template needs browser authorization before its tools become available.
#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub enum Installation {
    /// The installation is ready for discovery.
    Installed {
        /// ID of the new installation.
        id: Uuid,
    },
    /// The user must complete the browser authorization flow.
    Authorize {
        /// Authorization URL to open in the user's browser.
        redirect_url: String,
    },
}

/// Client for a project's connected MCP installations.
pub struct Gateway {
    api: ProjectEndpoint,
}

impl Gateway {
    /// Select an explicit PostHog project.
    pub fn new(origin: &str, project: u64) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::new(origin, project, "mcp_server_installations")?,
        })
    }

    /// Use the current project for the signed-in user.
    pub fn current(origin: &str) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::current(origin, "mcp_server_installations")?,
        })
    }

    /// Install a known template for the current user using PostHog's desktop response format.
    /// The caller owns the browser flow, credentials and any subsequent discovery.
    pub async fn install_personal_template(
        &self,
        token: &str,
        template: Uuid,
        api_key: Option<&str>,
    ) -> Result<Installation> {
        let mut body =
            json!({"template_id":template, "scope":"personal", "install_source":"posthog-code"});
        if let Some(key) = api_key {
            body["api_key"] = json!(key);
        }
        self.api.post(token, "install_template/", body).await
    }

    /// Discover installations and their advertised tools for this token.
    pub async fn available(&self, token: &str) -> Result<Vec<Server>> {
        #[derive(Deserialize)]
        struct Discovery {
            servers: Vec<Server>,
        }
        let result: Discovery = self.api.get(token, "available_tools/").await?;
        Ok(result.servers)
    }

    /// Invoke the advertised upstream name on this exact installation under the supplied user's grant.
    pub async fn call(
        &self,
        token: &str,
        installation: Uuid,
        name: &str,
        arguments: &Map<String, Value>,
    ) -> Result<ToolResult> {
        self.api
            .post(
                token,
                &format!("{installation}/call_tool/"),
                json!({"tool_name":name,"arguments":arguments}),
            )
            .await
    }
}

/// Project-scoped MCP store settings.
pub mod store;
