//! Identity: who is calling. No OAuth flow of our own — identity is established at
//! the edge and reaches us as headers, in this priority order:
//!
//! 1. `Tailscale-User-Login` — injected by the Tailscale ingress proxy (`whois: true`).
//!    Trusted only when `PGAPI_TRUST_TAILSCALE=1`, which must be paired with a
//!    NetworkPolicy admitting only `tailscale.com/managed=true` proxy pods.
//! 2. `x-amzn-oidc-data` — the ALB+Cognito JWT (`ingress.internal: true`). Verified
//!    (ES256) against the regional ALB public-key endpoint; never trusted unverified.
//! 3. `X-Auth-Request-Email` — the in-cluster auth gateway (heimdall). Trusted only
//!    when `PGAPI_TRUST_GATEWAY=1` (NetworkPolicy to the gateway's Envoy).
//! 4. `PGAPI_DEV_USER` in dev mode.
//!
//! Then authorisation: the email must match an allowed domain or the explicit list.
//! Everything the API serves is read-only, so there is one role today.

use crate::AppState;
use axum::{
    body::Body,
    extract::State,
    http::{Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

#[derive(Debug, Clone, Serialize)]
pub struct Principal {
    pub email: String,
    pub source: &'static str,
}

pub struct AlbConfig {
    pub region: String,
    pub client_id: String,
    /// ARN of the ALB that fronts this service; the token's `signer` header must match,
    /// otherwise a token minted by another ALB in the region with the same client id
    /// would be accepted.
    pub arn: String,
    /// kid → PEM public key, cached.
    pub keys: RwLock<HashMap<String, String>>,
}

pub struct AuthConfig {
    pub allowed_domains: Vec<String>,
    pub allowed_emails: Vec<String>,
    pub trust_tailscale: bool,
    /// Hosts (from the `Host` header) on which `Tailscale-User-Login` is trusted.
    /// Empty = any host ending in `.ts.net`. A request arriving on the Cognito
    /// ingress host can carry a forged header, so the header only counts on the
    /// tailnet host that the Tailscale proxy terminates.
    pub tailscale_hosts: Vec<String>,
    pub trust_gateway: bool,
    pub alb: Option<AlbConfig>,
    pub dev_user: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AlbClaims {
    email: Option<String>,
    #[serde(default)]
    email_verified: Option<serde_json::Value>,
    iss: String,
}

impl AuthConfig {
    fn authorized(&self, email: &str) -> bool {
        let email = email.to_ascii_lowercase();
        if self
            .allowed_emails
            .iter()
            .any(|e| e.eq_ignore_ascii_case(&email))
        {
            return true;
        }
        if self.allowed_domains.is_empty() {
            return true;
        }
        email
            .rsplit_once('@')
            .map(|(_, d)| {
                self.allowed_domains
                    .iter()
                    .any(|a| a.eq_ignore_ascii_case(d))
            })
            .unwrap_or(false)
    }

    fn on_tailscale_host(&self, headers: &axum::http::HeaderMap) -> bool {
        let host = headers
            .get("host")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .split(':')
            .next()
            .unwrap_or("")
            .to_ascii_lowercase();
        if self.tailscale_hosts.is_empty() {
            host.ends_with(".ts.net")
        } else {
            self.tailscale_hosts
                .iter()
                .any(|h| h.eq_ignore_ascii_case(&host))
        }
    }

    async fn identify(
        &self,
        headers: &axum::http::HeaderMap,
    ) -> Result<Principal, (StatusCode, String)> {
        let h = |n: &str| {
            headers
                .get(n)
                .and_then(|v| v.to_str().ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        };

        if self.trust_tailscale && self.on_tailscale_host(headers) {
            if let Some(login) = h("tailscale-user-login") {
                return Ok(Principal {
                    email: login,
                    source: "tailscale",
                });
            }
        }
        if let Some(alb) = &self.alb {
            if let Some(token) = h("x-amzn-oidc-data") {
                let email = verify_alb_token(alb, &token)
                    .await
                    .map_err(|e| (StatusCode::UNAUTHORIZED, format!("invalid ALB token: {e}")))?;
                return Ok(Principal {
                    email,
                    source: "cognito",
                });
            }
        }
        if self.trust_gateway {
            if let Some(email) = h("x-auth-request-email") {
                return Ok(Principal {
                    email,
                    source: "gateway",
                });
            }
        }
        if let Some(u) = &self.dev_user {
            return Ok(Principal {
                email: u.clone(),
                source: "dev",
            });
        }
        Err((
            StatusCode::UNAUTHORIZED,
            "no identity: reach this service through the internal ingress or the tailnet".into(),
        ))
    }
}

/// ALB signs `x-amzn-oidc-data` with ES256; the public key is served per `kid` at
/// https://public-keys.auth.elb.<region>.amazonaws.com/<kid>. The header's base64
/// segments may lack padding, and ALB's signature uses the raw (r,s) form
/// jsonwebtoken expects, so the standard decoder works after padding fix-up.
async fn verify_alb_token(alb: &AlbConfig, token: &str) -> anyhow::Result<String> {
    use jsonwebtoken::{decode, decode_header, Algorithm, DecodingKey, Validation};
    let token = fix_padding(token);
    let header = decode_header(&token)?;
    anyhow::ensure!(
        header.alg == Algorithm::ES256,
        "unexpected alg {:?}",
        header.alg
    );
    let kid = header
        .kid
        .ok_or_else(|| anyhow::anyhow!("token has no kid"))?;
    anyhow::ensure!(
        kid.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'),
        "bad kid"
    );
    let pem = {
        let cached = alb.keys.read().unwrap().get(&kid).cloned();
        match cached {
            Some(p) => p,
            None => {
                let url = format!(
                    "https://public-keys.auth.elb.{}.amazonaws.com/{kid}",
                    alb.region
                );
                let p = reqwest::Client::new()
                    .get(&url)
                    .send()
                    .await?
                    .error_for_status()?
                    .text()
                    .await?;
                alb.keys.write().unwrap().insert(kid.clone(), p.clone());
                p
            }
        }
    };
    let key = DecodingKey::from_ec_pem(pem.as_bytes())?;
    let mut v = Validation::new(Algorithm::ES256);
    v.validate_exp = true;
    v.set_required_spec_claims(&["exp"]);
    let data = decode::<AlbClaims>(&token, &key, &v)?;
    // Issuer must be a Cognito user pool in the ALB's region.
    let want_iss = format!("https://cognito-idp.{}.amazonaws.com/", alb.region);
    anyhow::ensure!(
        data.claims.iss.starts_with(&want_iss),
        "unexpected issuer {}",
        data.claims.iss
    );
    // The token must be minted for our app client by our ALB; both are recorded in the
    // JOSE header (`client`, `signer`) that the signature covers.
    let got = header_field(&token, "client")
        .ok_or_else(|| anyhow::anyhow!("token has no client in header"))?;
    anyhow::ensure!(alb.client_id == got, "token for another client ({got})");
    let signer = header_field(&token, "signer")
        .ok_or_else(|| anyhow::anyhow!("token has no signer in header"))?;
    anyhow::ensure!(
        alb.arn == signer,
        "token signed by another load balancer ({signer})"
    );
    let email = data
        .claims
        .email
        .ok_or_else(|| anyhow::anyhow!("token has no email claim"))?;
    // Cognito emits email_verified as a bool or as the strings "true"/"false"; only an
    // explicit true is a verified address. Missing means unverified.
    let verified = match &data.claims.email_verified {
        Some(serde_json::Value::Bool(b)) => *b,
        Some(serde_json::Value::String(s)) => s.eq_ignore_ascii_case("true"),
        _ => false,
    };
    anyhow::ensure!(verified, "email not verified");
    Ok(email)
}

/// ALB puts the Cognito app client id (`client`) and its own ARN (`signer`) in the JOSE header.
fn header_field(token: &str, key: &str) -> Option<String> {
    use base64::Engine;
    let h = token.split('.').next()?;
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(h.trim_end_matches('='))
        .ok()?;
    serde_json::from_slice::<serde_json::Value>(&bytes)
        .ok()?
        .get(key)?
        .as_str()
        .map(str::to_string)
}

fn fix_padding(token: &str) -> String {
    token
        .split('.')
        .map(|p| p.trim_end_matches('='))
        .collect::<Vec<_>>()
        .join(".")
}

pub async fn require_identity(
    State(state): State<Arc<AppState>>,
    mut req: Request<Body>,
    next: Next,
) -> Response {
    if !state.allowed_hosts.is_empty() {
        let host = req
            .headers()
            .get("host")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .split(':')
            .next()
            .unwrap_or("")
            .to_string();
        if !state
            .allowed_hosts
            .iter()
            .any(|h| h.eq_ignore_ascii_case(&host))
        {
            return (StatusCode::FORBIDDEN, format!("host {host} not allowed")).into_response();
        }
    }
    let headers = req.headers().clone(); // Body is !Sync; don't hold &Request across awaits
    match state.auth.identify(&headers).await {
        Ok(p) => {
            if !state.auth.authorized(&p.email) {
                tracing::warn!(email = p.email, source = p.source, "forbidden");
                return (
                    StatusCode::FORBIDDEN,
                    format!("{} is not allowed to read pgcollector data", p.email),
                )
                    .into_response();
            }
            tracing::info!(email = p.email, source = p.source, method = %req.method(), path = %req.uri().path(), "request");
            req.extensions_mut().insert(p);
            next.run(req).await
        }
        Err((code, msg)) => (code, msg).into_response(),
    }
}
