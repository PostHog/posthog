use axum::response::Html;

pub async fn index() -> Html<&'static str> {
    Html(include_str!("ui/index.html"))
}

/// The ingestion-consumer's debug UI, served per pod at `/pods/:name/` so its
/// relative `debug/...` fetches resolve to this service's per-pod proxy. The
/// UI lives here (the control plane); the consumer only exposes the debug API.
pub async fn consumer_debug() -> Html<&'static str> {
    Html(include_str!("ui/consumer_debug.html"))
}
