use axum::extract::Request;
use axum::middleware::Next;
use axum::response::Response;
use metrics::counter;

/// `X-PostHog-Client-IP` is added to every request the Cloudflare managed-reverse-proxy
/// Worker forwards (so PostHog can attribute the real client IP). Only that Worker sets it,
/// so its presence marks a request as served via the Cloudflare proxy — as opposed to the
/// legacy in-cluster proxy or a direct client.
///
/// This layer counts requests by that provenance so we can measure Cloudflare read vs ingest
/// volume (per-service: capture = ingest, feature-flags = flag reads) WITHOUT enabling the
/// paid Cloudflare Workers Logs. Metrics-only: we check header presence, not the signature,
/// so no verification/secret is needed here.
const MANAGED_PROXY_CLIENT_IP_HEADER: &str = "x-posthog-client-ip";

pub async fn track_managed_proxy(request: Request, next: Next) -> Response {
    let via_managed_proxy = if request.headers().contains_key(MANAGED_PROXY_CLIENT_IP_HEADER) {
        "true"
    } else {
        "false"
    };
    // Scrape labels (namespace/pod) identify the emitting service, so no service label here.
    counter!("managed_proxy_requests_total", "via_managed_proxy" => via_managed_proxy).increment(1);
    next.run(request).await
}
