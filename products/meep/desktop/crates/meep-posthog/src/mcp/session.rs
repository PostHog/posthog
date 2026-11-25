//! Authenticated PostHog MCP sessions over Streamable HTTP.
use crate::{api::ApiError, mcp::ToolResult};
use anyhow::{Context, Result, bail, ensure};
use futures_util::StreamExt;
use reqwest::{
    Body, Client, Response,
    header::{ACCEPT, CONTENT_TYPE, HeaderValue},
    redirect::Policy,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sse_stream::SseStream;
use std::{collections::HashSet, time::Duration};
use url::Url;

/// The hosted PostHog MCP server for OAuth users.
pub const DEFAULT_ENDPOINT: &str = "https://mcp.posthog.com/mcp";
const PROTOCOL: &str = "2025-11-25";

/// A tool actually advertised to the authenticated account.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct McpTool {
    /// Exact name to pass to `tools/call`.
    pub name: String,
    /// JSON Schema describing the tool arguments.
    pub input_schema: Value,
}

/// Transport for a configured PostHog MCP endpoint and optional project pin.
#[derive(Clone)]
pub struct McpClient {
    http: Client,
    endpoint: Url,
}

impl McpClient {
    /// Select the hosted or self-hosted endpoint. Plain HTTP is allowed on loopback.
    /// A project pin selects the account's project for the entire session.
    pub fn new(endpoint: &str, project: Option<u64>) -> Result<Self> {
        let mut url = Url::parse(endpoint)?;
        ensure!(
            url.has_host()
                && url.username().is_empty()
                && url.password().is_none()
                && url.fragment().is_none()
                && crate::is_https_or_loopback(&url),
            "invalid PostHog MCP endpoint"
        );
        if let Some(project) = project {
            ensure!(project > 0, "invalid PostHog project ID");
            let pin = project.to_string();
            let mut present = false;
            for (_, value) in url.query_pairs().filter(|(key, _)| key == "project_id") {
                ensure!(!present && value == pin, "conflicting MCP project_id");
                present = true;
            }
            if !present {
                url.query_pairs_mut().append_pair("project_id", &pin);
            }
        }
        let http = Client::builder()
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .timeout(Duration::from_secs(30))
            .build()?;
        Ok(Self {
            http,
            endpoint: url,
        })
    }

    /// Negotiate the protocol with a person's OAuth token and acknowledge initialization.
    pub async fn initialize(&self, token: &str) -> Result<McpSession> {
        let mut session = McpSession {
            client: self.clone(),
            token: token.to_owned(),
            id: None,
            protocol: None,
            sequence: 0,
        };
        let result = session
            .request(
                "initialize",
                json!({"protocolVersion":PROTOCOL,
            "capabilities":{},"clientInfo":{"name":"meep","version":env!("CARGO_PKG_VERSION")}}),
            )
            .await?;
        let version = result["protocolVersion"]
            .as_str()
            .context("MCP initialize omitted protocolVersion")?;
        ensure!(
            matches!(version, PROTOCOL | "2025-06-18" | "2025-03-26"),
            "unsupported MCP protocol {version}"
        );
        session.protocol = Some(version.to_owned());
        session
            .post(json!({"jsonrpc":"2.0","method":"notifications/initialized"}))
            .await?;
        Ok(session)
    }
}

/// An initialized session retaining its bearer credential, session ID and protocol version.
pub struct McpSession {
    client: McpClient,
    token: String,
    id: Option<HeaderValue>,
    protocol: Option<String>,
    sequence: u64,
}

impl McpSession {
    /// Discover tools across all pages, rejecting repeated pagination cursors.
    pub async fn list_tools(&mut self) -> Result<Vec<McpTool>> {
        #[derive(Serialize, Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct Page {
            tools: Vec<McpTool>,
            next_cursor: Option<String>,
        }
        let mut tools = vec![];
        let mut params = json!({});
        let mut seen = HashSet::new();
        loop {
            let page: Page = serde_json::from_value(self.request("tools/list", params).await?)
                .context("invalid MCP tool list")?;
            tools.extend(page.tools);
            let Some(cursor) = page.next_cursor.filter(|c| !c.is_empty()) else {
                break;
            };
            ensure!(
                seen.insert(cursor.clone()),
                "MCP server repeated a tools/list cursor"
            );
            params = json!({"cursor":cursor});
        }
        Ok(tools)
    }

    /// Call a discovered tool with JSON object arguments.
    pub async fn call(&mut self, name: &str, arguments: Value) -> Result<ToolResult> {
        ensure!(arguments.is_object(), "MCP arguments must be an object");
        let value = self
            .request("tools/call", json!({"name":name,"arguments":arguments}))
            .await
            .with_context(|| format!("calling MCP tool {name}"))?;
        serde_json::from_value(value).context("invalid MCP tool result")
    }

    async fn post(&self, message: Value) -> Result<Response> {
        let mut req = self
            .client
            .http
            .post(self.client.endpoint.clone())
            .bearer_auth(&self.token)
            .header(ACCEPT, "application/json, text/event-stream")
            .header("x-posthog-mcp-mode", "tools")
            .json(&message);
        if let Some(id) = &self.id {
            req = req.header("mcp-session-id", id);
        }
        if let Some(version) = &self.protocol {
            req = req.header("mcp-protocol-version", version);
        }
        let response = req
            .send()
            .await
            .context("could not reach the PostHog MCP server")?;
        let status = response.status();
        if !status.is_success() {
            let body = response.json::<Value>().await.unwrap_or(Value::Null);
            let detail = body
                .pointer("/error/message")
                .or_else(|| body.get("detail"))
                .or_else(|| body.get("error"))
                .and_then(Value::as_str)
                .unwrap_or_else(|| status.canonical_reason().unwrap_or("request failed"));
            return Err(ApiError {
                status: status.as_u16(),
                code: "MCP".into(),
                detail: detail.to_owned(),
            }
            .into());
        }
        Ok(response)
    }

    async fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        self.sequence += 1;
        let id = self.sequence;
        let response = self
            .post(json!({"jsonrpc":"2.0","method":method,"params":params,"id":id}))
            .await?;
        if method == "initialize" {
            self.id = response.headers().get("mcp-session-id").cloned();
        }
        let mime = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|h| h.to_str().ok())
            .and_then(|s| s.split(';').next())
            .unwrap_or_default()
            .trim();
        let message = if mime.eq_ignore_ascii_case("application/json") {
            response
                .json::<Value>()
                .await
                .context("invalid MCP JSON response")?
        } else if mime.eq_ignore_ascii_case("text/event-stream") {
            let mut stream = SseStream::new(Body::from(response));
            loop {
                let event = stream
                    .next()
                    .await
                    .context("MCP event stream ended before the response")??;
                if let Some(data) = event.data.filter(|s| !s.trim().is_empty()) {
                    let message: Value =
                        serde_json::from_str(&data).context("invalid MCP event data")?;
                    if message["id"] == id && message.get("method").is_none() {
                        break message;
                    }
                }
            }
        } else {
            bail!("unexpected MCP response content type '{mime}'");
        };
        ensure!(
            message["jsonrpc"] == "2.0" && message["id"] == id,
            "invalid or mismatched MCP response to {method}"
        );
        if let Some(error) = message.get("error") {
            bail!(
                "MCP {method} failed ({}): {}",
                error["code"],
                error["message"].as_str().unwrap_or("server error")
            );
        }
        message
            .get("result")
            .cloned()
            .with_context(|| format!("MCP {method} response omitted result"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bearer_endpoints_require_https_or_loopback_and_exclude_url_credentials() {
        for endpoint in [
            "http://example.com/mcp",
            "https://me:pass@example.com/mcp",
            "https://example.com/mcp#frag",
            "file:///mcp",
        ] {
            assert!(McpClient::new(endpoint, None).is_err(), "{endpoint}");
        }
        for endpoint in [
            DEFAULT_ENDPOINT,
            "http://127.0.0.1:8400/mcp",
            "http://[::1]/mcp",
        ] {
            assert!(McpClient::new(endpoint, None).is_ok(), "{endpoint}");
        }
    }

    #[test]
    fn a_project_pin_preserves_tool_filters_and_refuses_conflicting_accounts() -> Result<()> {
        let endpoint = "https://example.com/mcp?tools=insight-query";
        let pinned = McpClient::new(endpoint, Some(8))?;
        assert_eq!(
            pinned.endpoint.query(),
            Some("tools=insight-query&project_id=8")
        );
        assert_eq!(
            McpClient::new(pinned.endpoint.as_str(), Some(8))?.endpoint,
            pinned.endpoint
        );
        assert!(McpClient::new(pinned.endpoint.as_str(), Some(9)).is_err());
        assert!(McpClient::new(endpoint, Some(0)).is_err());
        Ok(())
    }
}
