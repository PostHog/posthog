use sqlx::Row;

/// Per-team error-tracking rate-limit configuration, loaded from
/// `posthog_errortrackingsettings`. Two independent limits, matching the Node.js
/// limiter: a per-issue cap and a project-wide (team) cap. A `None` value for a
/// limit means that limit is disabled for the team.
#[derive(Debug, Clone, Default)]
pub struct RateLimitSettings {
    pub project_value: Option<i32>,
    pub project_bucket_minutes: Option<i32>,
    pub per_issue_value: Option<i32>,
    pub per_issue_bucket_minutes: Option<i32>,
}

/// Token-bucket parameters for one limit: `max` is the burst size (bucket
/// capacity), `rate` is the steady refill in tokens/second.
#[derive(Debug, Clone, Copy)]
pub struct BucketParams {
    pub max: f64,
    pub rate: f64,
}

impl RateLimitSettings {
    fn to_bucket_params(value: Option<i32>, minutes: Option<i32>) -> Option<BucketParams> {
        let value = value?;
        if value <= 0 {
            return None;
        }
        // "value events per `minutes` minutes" → bucket size `value`,
        // refill `value / (minutes * 60)` tokens per second.
        let minutes = minutes.unwrap_or(60).max(1);
        Some(BucketParams {
            max: value as f64,
            rate: value as f64 / (minutes as f64 * 60.0),
        })
    }

    pub fn per_issue(&self) -> Option<BucketParams> {
        Self::to_bucket_params(self.per_issue_value, self.per_issue_bucket_minutes)
    }

    pub fn project(&self) -> Option<BucketParams> {
        Self::to_bucket_params(self.project_value, self.project_bucket_minutes)
    }

    pub async fn load_for_team<'c, E>(conn: E, team_id: i32) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let row = sqlx::query(
            "SELECT project_rate_limit_value, project_rate_limit_bucket_size_minutes, \
                    per_issue_rate_limit_value, per_issue_rate_limit_bucket_size_minutes \
             FROM posthog_errortrackingsettings WHERE team_id = $1",
        )
        .bind(team_id)
        .fetch_optional(conn)
        .await?;

        row.map(|r| {
            Ok(Self {
                project_value: r.try_get("project_rate_limit_value")?,
                project_bucket_minutes: r.try_get("project_rate_limit_bucket_size_minutes")?,
                per_issue_value: r.try_get("per_issue_rate_limit_value")?,
                per_issue_bucket_minutes: r.try_get("per_issue_rate_limit_bucket_size_minutes")?,
            })
        })
        .transpose()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_when_value_missing_or_nonpositive() {
        let s = RateLimitSettings::default();
        assert!(s.per_issue().is_none());
        assert!(s.project().is_none());

        let s = RateLimitSettings {
            project_value: Some(0),
            ..Default::default()
        };
        assert!(s.project().is_none());
    }

    #[test]
    fn bucket_params_from_value_and_minutes() {
        let s = RateLimitSettings {
            project_value: Some(120),
            project_bucket_minutes: Some(2),
            per_issue_value: Some(60),
            per_issue_bucket_minutes: None, // defaults to 60 minutes
        };

        let project = s.project().unwrap();
        assert_eq!(project.max, 120.0);
        assert!((project.rate - 1.0).abs() < 1e-9); // 120 / (2*60) = 1/s

        let per_issue = s.per_issue().unwrap();
        assert_eq!(per_issue.max, 60.0);
        assert!((per_issue.rate - (60.0 / 3600.0)).abs() < 1e-9);
    }
}
