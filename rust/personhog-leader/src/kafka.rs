/// Formats the Kafka message key for person state changelog messages.
/// The topic must include `compact` in its `cleanup.policy` so Kafka
/// retains the latest state per person. Deployed config is
/// `compact,delete`, where retention bounds even the latest record —
/// acceptable because nothing reads records older than the writer's
/// committed offset, which retention outruns by design.
pub fn changelog_message_key(team_id: i64, person_id: i64) -> String {
    format!("{team_id}:{person_id}")
}
