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
