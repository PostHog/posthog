use sqlx::{types::Uuid, Executor, Postgres};
use std::hash::Hash;

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub struct ErrorTrackingGroup {
    pub fingerprint: String,
    pub team_id: i32,
}

impl Hash for ErrorTrackingGroup {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.fingerprint.hash(state);
    }
}

impl ErrorTrackingGroup {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        sqlx::query!(
            r#"
            INSERT INTO posthog_errortrackinggroup (id, fingerprint, team_id, created_at)
            VALUES ($1, $2, $3, NOW()) ON CONFLICT
            ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq
            DO UPDATE SET created_at = $4
        "#,
            Uuid::now_v7(),
            self.fingerprint,
            self.team_id,
        )
        .execute(executor)
        .await
        .map(|_| ())
    }
}
