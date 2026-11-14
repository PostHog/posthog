/// Logs at `info!` level with "CHATTY: " prefix when enabled, otherwise `debug!` level.
/// Accepts the same syntax as tracing macros: `debug_or_info!(flag, field=?value, "message")`
#[macro_export]
macro_rules! debug_or_info {
    ($enabled:expr, $($args:tt)+) => {
        $crate::debug_or_info!(@parse $enabled, [] $($args)+)
    };

    (@parse $enabled:expr, [$($fields:tt)*] $msg:literal) => {
        if $enabled {
            ::tracing::info!($($fields)* concat!("CHATTY: ", $msg));
        } else {
            ::tracing::debug!($($fields)* $msg);
        }
    };

    (@parse $enabled:expr, [$($fields:tt)*] $next:tt $($rest:tt)+) => {
        $crate::debug_or_info!(@parse $enabled, [$($fields)* $next] $($rest)+)
    };
}

const LOGGABLE_HEADERS: [&str; 4] = [
    "content-type",
    "content-encoding",
    "user-agent",
    "x-request-id",
];

/// Formats only the request headers that capture reads, so request logs never
/// carry cookies, credentials, or other headers a client or proxy forwards.
pub struct LoggableHeaders<'a>(pub &'a axum::http::HeaderMap);

impl std::fmt::Debug for LoggableHeaders<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_map()
            .entries(
                LOGGABLE_HEADERS
                    .iter()
                    .filter_map(|name| self.0.get(*name).map(|value| (name, value))),
            )
            .finish()
    }
}
