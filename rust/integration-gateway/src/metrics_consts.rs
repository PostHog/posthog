/// `result` label values: "ok" | "error". `caller` label = the JWT `caller` claim.
pub const FETCH_TOTAL: &str = "integration_gateway_fetch_total";

/// Token-refresh outcomes. `result` label: "refreshed" | "failed" | "locked" | "skipped".
/// `kind` label = the integration kind.
pub const REFRESH_TOTAL: &str = "integration_gateway_refresh_total";
