use crate::{WatchMode, mapping::Mapping, validate_watches};
use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Utc};
use hmac::{Hmac, Mac};
use http::{HeaderMap, header::HeaderName};
use meep_ingest::Event;
use meep_topic::{TopicId, Watch};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use thiserror::Error;

/// Workflow webhook errors that the host can map to an HTTP response.
#[derive(Debug, Error)]
pub enum WebhookError {
    /// The required header is absent, ambiguous, or failed verification.
    #[error("webhook authentication failed")]
    Unauthorized,
    /// The authenticated payload could not be mapped to events.
    #[error("invalid webhook payload: {0:#}")]
    InvalidPayload(#[source] anyhow::Error),
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Config {
    connection: String,
    watch: Option<Watch>,
    #[serde(default)]
    watches: Vec<Watch>,
    mode: Option<WatchMode>,
    mapping: Option<Mapping>,
    preset: Option<Preset>,
    auth: Option<Auth>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Preset {
    PosthogWorkflow,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Auth {
    HmacSha256 { header: String },
    SharedSecret { header: String },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct WorkflowEvent {
    topic_hint: Option<TopicId>,
    source: WorkflowSource,
    author: String,
    at: DateTime<Utc>,
    text: String,
    external_id: String,
    thread_hint: Option<String>,
    #[serde(default)]
    attributes: Map<String, Value>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct WorkflowSource {
    service: String,
    kind: String,
    key: String,
}

pub(super) struct Webhook {
    connection: String,
    watches: Vec<Watch>,
    mapping: Option<Mapping>,
    auth: Auth,
    header: HeaderName,
    secret: String,
}

impl Webhook {
    pub fn new(config: Value, secret: String) -> Result<Self> {
        let mut config: Config =
            serde_json::from_value(config).context("invalid workflow webhook configuration")?;
        if let Some(watch) = config.watch {
            ensure!(config.watches.is_empty(), "use either watch or watches");
            config.watches.push(watch);
        }
        validate_watches(&config.connection, &config.watches)?;
        ensure!(
            config.mode != Some(WatchMode::Pull),
            "workflow webhooks only support push mode"
        );
        if let Some(mapping) = &config.mapping {
            ensure!(
                config.preset.is_none() && config.watches.len() == 1,
                "custom workflow mappings require one watch and no preset"
            );
            mapping.validate()?;
        }
        let auth = config.auth.unwrap_or_else(|| Auth::SharedSecret {
            header: "x-meep-secret".into(),
        });
        let (Auth::SharedSecret { header } | Auth::HmacSha256 { header }) = &auth;
        Ok(Self {
            header: header.parse().context("invalid webhook header name")?,
            connection: config.connection,
            watches: config.watches,
            mapping: config.mapping,
            auth,
            secret,
        })
    }

    pub fn receive(&self, headers: &HeaderMap, body: &[u8]) -> Result<Vec<Event>> {
        let mut values = headers.get_all(&self.header).iter();
        let header = values
            .next()
            .filter(|_| values.next().is_none())
            .ok_or(WebhookError::Unauthorized)?
            .as_bytes();
        match self.auth {
            Auth::SharedSecret { .. } => {
                ensure!(
                    bool::from(
                        Sha256::digest(header).ct_eq(&Sha256::digest(self.secret.as_bytes()))
                    ),
                    WebhookError::Unauthorized
                );
            }
            Auth::HmacSha256 { .. } => {
                let encoded = header.strip_prefix(b"sha256=").unwrap_or(header);
                let mut digest = [0; 32];
                hex::decode_to_slice(encoded, &mut digest)
                    .map_err(|_| WebhookError::Unauthorized)?;
                let mut mac = Hmac::<Sha256>::new_from_slice(self.secret.as_bytes())?;
                mac.update(body);
                mac.verify_slice(&digest)
                    .map_err(|_| WebhookError::Unauthorized)?;
            }
        }
        self.decode(body)
            .map_err(|e| WebhookError::InvalidPayload(e).into())
    }

    fn decode(&self, body: &[u8]) -> Result<Vec<Event>> {
        if let Some(mapping) = &self.mapping {
            let watch = self
                .watches
                .first()
                .context("missing workflow mapping watch")?;
            return Ok(mapping
                .rows(&serde_json::from_slice(body)?, watch)?
                .into_iter()
                .map(|r| r.event)
                .collect());
        }
        let mut payload: WorkflowEvent = serde_json::from_slice(body)?;
        let source = &payload.source;
        ensure!(
            [
                &source.service,
                &source.kind,
                &source.key,
                &payload.external_id,
                &payload.author
            ]
            .iter()
            .all(|s| !s.trim().is_empty()),
            "workflow source, external_id and author must be nonempty"
        );
        if !self.watches.is_empty()
            && !self
                .watches
                .iter()
                .any(|w| w.kind == source.kind && w.key == source.key)
        {
            return Ok(vec![]);
        }
        // The authenticated connection and configured watches determine routing.
        // Preserve provenance and optional topic hint for the host.
        payload.attributes.insert("source".into(), json!(source));
        payload.attributes.remove("topic_hint");
        if let Some(topic) = payload.topic_hint {
            payload.attributes.insert("topic_hint".into(), json!(topic));
        }
        Ok(vec![Event {
            connection: self.connection.clone(),
            kind: payload.source.kind,
            channel: payload.source.key,
            external_id: payload.external_id,
            thread_hint: payload.thread_hint,
            author: payload.author,
            at: payload.at,
            text: payload.text,
            attributes: Value::Object(payload.attributes),
        }])
    }
}
