const DEFAULT_SPIKE_MULTIPLIER: f64 = 10.0;
const DEFAULT_MIN_SPIKE_THRESHOLD: i64 = 500;
const DEFAULT_SPIKE_ALERT_COOLDOWN_SECONDS: usize = 10 * 60;

#[derive(Debug, Clone)]
pub struct SpikeDetectionConfig {
    pub multiplier: f64,
    pub threshold: i64,
    pub snooze_duration_seconds: usize,
}

impl Default for SpikeDetectionConfig {
    fn default() -> Self {
        Self {
            multiplier: DEFAULT_SPIKE_MULTIPLIER,
            threshold: DEFAULT_MIN_SPIKE_THRESHOLD,
            snooze_duration_seconds: DEFAULT_SPIKE_ALERT_COOLDOWN_SECONDS,
        }
    }
}

impl SpikeDetectionConfig {
    pub async fn load_for_team<'c, E>(conn: E, team_id: i32) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let row = sqlx::query!(
            r#"
                SELECT multiplier, threshold, snooze_duration_minutes
                FROM posthog_errortrackingspikedetectionconfig
                WHERE team_id = $1
            "#,
            team_id
        )
        .fetch_optional(conn)
        .await?;

        Ok(row.map(|r| Self {
            multiplier: r.multiplier as f64,
            threshold: r.threshold as i64,
            snooze_duration_seconds: (r.snooze_duration_minutes * 60) as usize,
        }))
    }
}
