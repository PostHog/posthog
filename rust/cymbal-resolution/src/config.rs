use std::net::SocketAddr;

use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// gRPC bind address for the cymbal.resolution.v1 server.
    #[envconfig(from = "GRPC_ADDRESS", default = "0.0.0.0:50061")]
    pub grpc_address: SocketAddr,

    /// HTTP bind port for liveness, readiness, and Prometheus metrics.
    #[envconfig(from = "METRICS_PORT", default = "9101")]
    pub metrics_port: u16,

    /// Cap on concurrent gRPC requests accepted by the server before fast
    /// load shedding kicks in. Beyond this, callers receive `UNAVAILABLE`
    /// and retry against another pod — preferred over hidden queue growth
    /// on the symbol-resolution semaphore. Zero disables the limit; the
    /// non-zero default keeps fail-fast semantics by default.
    #[envconfig(from = "MAX_CONCURRENT_REQUESTS", default = "256")]
    pub max_concurrent_requests: usize,

    /// Cap on concurrent symbol-resolution operations across all in-flight
    /// requests. Reuses the same semantic as cymbal's
    /// `SYMBOL_RESOLUTION_CONCURRENCY` knob. Items beyond this wait on the
    /// internal semaphore until the request deadline; sustained pressure
    /// surfaces as caller-retryable `Retry { code = "overloaded" }` outcomes
    /// when the limiter is closed.
    #[envconfig(from = "SYMBOL_RESOLUTION_CONCURRENCY", default = "64")]
    pub symbol_resolution_concurrency: usize,

    /// Process-wide cap on concurrent item (exception) processing across all
    /// in-flight `Resolve` requests. Replaces the previous per-request
    /// `REQUEST_ITEM_CONCURRENCY` so total item parallelism stays bounded
    /// regardless of how many concurrent RPCs are open. Symbol work is
    /// governed separately by `SYMBOL_RESOLUTION_CONCURRENCY`.
    #[envconfig(from = "MAX_ITEM_CONCURRENCY", default = "64")]
    pub max_item_concurrency: usize,

    /// Server self-marks `LoadEvent.degraded` once the item semaphore's
    /// in-flight ratio crosses this value, so callers can route away
    /// preemptively before the gRPC admission queue load-sheds with
    /// `UNAVAILABLE`. Values are clamped to `(0.0, 1.0]` at use sites.
    #[envconfig(from = "DEGRADED_LOAD_RATIO", default = "0.8")]
    pub degraded_load_ratio: f64,

    /// Service instance identifier surfaced to callers via `LoadEvent` on
    /// the Subscribe stream. Defaults to a random uuid generated at boot
    /// when not provided.
    #[envconfig(from = "SERVICE_INSTANCE_ID")]
    pub service_instance_id: Option<String>,

    /// Default cadence for the load event bus (`Subscribe` RPC) in
    /// milliseconds. Callers may suggest a cadence via
    /// `SubscribeRequest.tick_hint_ms`; the server clamps to
    /// `[subscribe_min_tick_ms, subscribe_max_tick_ms]` so a misbehaving
    /// caller cannot induce excess work.
    #[envconfig(from = "SUBSCRIBE_TICK_INTERVAL_MS", default = "1000")]
    pub subscribe_tick_interval_ms: u64,

    /// Lower bound for the load-event tick cadence. Hints below this are
    /// clamped up.
    #[envconfig(from = "SUBSCRIBE_MIN_TICK_MS", default = "100")]
    pub subscribe_min_tick_ms: u64,

    /// Upper bound for the load-event tick cadence. Hints above this are
    /// clamped down so a misconfigured caller cannot make the stream stale.
    #[envconfig(from = "SUBSCRIBE_MAX_TICK_MS", default = "10000")]
    pub subscribe_max_tick_ms: u64,
}
