mod api;
mod auth;
mod config;
mod db;
mod mcp;
mod queries;
mod ui;

use anyhow::Result;
use axum::{middleware, routing::get, Router};
use clap::Parser;
use std::sync::Arc;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(
    name = "pgapi",
    about = "API + MCP server over the pgcollector stats database"
)]
struct Cli {
    #[arg(long, env = "PGAPI_DATABASE_URL")]
    database_url: String,
    #[arg(long, env = "PGAPI_LISTEN", default_value = "0.0.0.0:3400")]
    listen: String,
    /// Comma-separated email domains allowed to read (empty = any authenticated identity).
    #[arg(
        long,
        env = "PGAPI_ALLOWED_DOMAINS",
        default_value = "posthog.com",
        value_delimiter = ','
    )]
    allowed_domains: Vec<String>,
    /// Comma-separated explicit allowlist of emails (in addition to domains).
    #[arg(long, env = "PGAPI_ALLOWED_EMAILS", value_delimiter = ',')]
    allowed_emails: Vec<String>,
    /// Trust `Tailscale-User-Login` from the Tailscale ingress proxy. Only enable with a
    /// NetworkPolicy that restricts ingress to the operator's proxy pods.
    #[arg(long, env = "PGAPI_TRUST_TAILSCALE", default_value = "false", value_parser = parse_bool)]
    trust_tailscale: bool,
    /// Hosts on which `Tailscale-User-Login` is trusted (comma-separated). Empty = any
    /// host ending in `.ts.net`.
    #[arg(long, env = "PGAPI_TAILSCALE_HOSTS", value_delimiter = ',')]
    tailscale_hosts: Vec<String>,
    /// Verify ALB/Cognito `x-amzn-oidc-data` tokens (region for the ALB public key endpoint).
    /// Requires PGAPI_ALB_CLIENT_ID.
    #[arg(long, env = "PGAPI_ALB_REGION", requires_all = ["alb_client_id", "alb_arn"])]
    alb_region: Option<String>,
    /// Cognito app client id the ALB tokens must be minted for.
    #[arg(long, env = "PGAPI_ALB_CLIENT_ID")]
    alb_client_id: Option<String>,
    /// ARN of the ALB in front of this service; tokens signed by any other ALB are rejected.
    #[arg(long, env = "PGAPI_ALB_ARN")]
    alb_arn: Option<String>,
    /// Trust `X-Auth-Request-Email` from the in-cluster auth gateway (heimdall).
    #[arg(long, env = "PGAPI_TRUST_GATEWAY", default_value = "false", value_parser = parse_bool)]
    trust_gateway: bool,
    /// DEV ONLY: treat every request as this user. Refused unless PGAPI_DEV_MODE=1.
    #[arg(long, env = "PGAPI_DEV_USER")]
    dev_user: Option<String>,
    #[arg(long, env = "PGAPI_DEV_MODE", default_value = "false", value_parser = parse_bool)]
    dev_mode: bool,
    /// Hosts this server may be addressed as (DNS-rebinding guard for /mcp). Empty = any.
    #[arg(long, env = "PGAPI_ALLOWED_HOSTS", value_delimiter = ',')]
    allowed_hosts: Vec<String>,
}

/// Accept 1/0/true/false/yes/no/on/off so Helm `env:` values like "1" work.
fn parse_bool(s: &str) -> Result<bool, String> {
    match s.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" | "" => Ok(false),
        o => Err(format!("expected a boolean, got {o:?}")),
    }
}

pub struct AppState {
    pub db: db::Db,
    pub auth: auth::AuthConfig,
    pub allowed_hosts: Vec<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    rustls::crypto::aws_lc_rs::default_provider()
        .install_default()
        .expect("failed to install rustls CryptoProvider");

    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| "info,tokio_postgres=warn".into()),
        )
        .init();
    let cli = Cli::parse();
    if cli.dev_user.is_some() && !cli.dev_mode {
        anyhow::bail!("PGAPI_DEV_USER requires PGAPI_DEV_MODE=1");
    }
    let auth = auth::AuthConfig {
        allowed_domains: cli
            .allowed_domains
            .into_iter()
            .filter(|d| !d.is_empty())
            .collect(),
        allowed_emails: cli
            .allowed_emails
            .into_iter()
            .filter(|d| !d.is_empty())
            .collect(),
        trust_tailscale: cli.trust_tailscale,
        tailscale_hosts: cli
            .tailscale_hosts
            .into_iter()
            .filter(|h| !h.is_empty())
            .collect(),
        trust_gateway: cli.trust_gateway,
        alb: match (cli.alb_region, cli.alb_client_id, cli.alb_arn) {
            (Some(region), Some(client_id), Some(arn)) => Some(auth::AlbConfig {
                region,
                client_id,
                arn,
                keys: Default::default(),
            }),
            _ => None,
        },
        dev_user: cli.dev_user,
    };
    if auth.dev_user.is_some() {
        tracing::warn!(
            "DEV MODE: all requests authenticated as {:?}",
            auth.dev_user
        );
    }
    if !auth.trust_tailscale && !auth.trust_gateway && auth.alb.is_none() && auth.dev_user.is_none()
    {
        tracing::warn!("no identity source configured (PGAPI_TRUST_TAILSCALE / PGAPI_ALB_REGION / dev mode): every request will be 401");
    }

    let db = db::Db::connect(&cli.database_url).await?;
    let state = Arc::new(AppState {
        db,
        auth,
        allowed_hosts: cli
            .allowed_hosts
            .into_iter()
            .filter(|h| !h.is_empty())
            .collect(),
    });

    let protected = Router::new()
        .route("/", get(ui::index))
        .nest("/api/v1", api::router())
        .nest_service("/mcp", mcp::service(state.clone()))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            auth::require_identity,
        ));

    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/readyz", get(api::readyz))
        .route("/metrics", get(api::metrics))
        .merge(protected)
        .layer(tower_http::trace::TraceLayer::new_for_http())
        .with_state(state);

    // Constant 1 with the crate version as a label, so dashboards can show which
    // build each pod runs without reading pod specs.
    prometheus::register_int_gauge_vec!("pgapi_build_info", "build metadata", &["version"])?
        .with_label_values(&[env!("CARGO_PKG_VERSION")])
        .set(1);

    let listener = tokio::net::TcpListener::bind(&cli.listen).await?;
    tracing::info!(
        listen = cli.listen,
        version = env!("CARGO_PKG_VERSION"),
        "pgapi listening"
    );
    axum::serve(listener, app).await?;
    Ok(())
}
