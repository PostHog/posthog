/// One credential-fetch audit record. Emitted for every request. Records who fetched which
/// integration ids and the resolution outcome — but NEVER any credential value. This is the
/// core near-term win: a durable-in-logs "who accessed which credential, when, on whose behalf".
pub struct AuditEvent<'a> {
    pub caller: &'a str,
    pub team_id: i64,
    pub requested: &'a [i64],
    pub resolved: &'a [i64],
    pub cache_hits: usize,
    pub db_loaded: usize,
    pub request_id: &'a str,
}

pub fn emit(ev: &AuditEvent) {
    tracing::info!(
        target: "integration_gateway::audit",
        caller = ev.caller,
        team_id = ev.team_id,
        requested = ?ev.requested,
        resolved = ?ev.resolved,
        cache_hits = ev.cache_hits,
        db_loaded = ev.db_loaded,
        request_id = ev.request_id,
        "credential_fetch"
    );
}
