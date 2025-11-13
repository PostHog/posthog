use sqlx::Postgres;
use uuid::Uuid;

use crate::app_context::AppContext;

#[derive(Debug, Clone)]
pub struct Organization {
    pub id: Uuid,
    pub is_ai_data_processing_approved: Option<bool>,
}

impl Organization {
    pub async fn for_team<'c, E>(e: E, team_id: i32) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            "SELECT
                o.id, o.is_ai_data_processing_approved
            FROM posthog_organization o
                JOIN posthog_team ON o.id = posthog_team.organization_id
            WHERE posthog_team.id = $1",
            team_id
        )
        .fetch_optional(e)
        .await
    }

    pub fn drop_if_not_ai_processing_approved<T>(&self, value: T) -> Option<T> {
        self.is_ai_data_processing_approved
            .unwrap_or_default()
            .then_some(value)
    }
}

pub async fn apply_ai_opt_in<T>(
    context: &AppContext,
    request: T,
    team_id: i32,
) -> Result<Option<T>, sqlx::Error> {
    let org = match context.org_cache.get(&team_id) {
        Some(Some(org)) => org,
        Some(None) => return Ok(None),
        None => {
            let org = Organization::for_team(&context.pool, team_id).await?;
            context.org_cache.insert(team_id, org.clone());
            let Some(org) = org else {
                return Ok(None);
            };
            org
        }
    };

    Ok(org.drop_if_not_ai_processing_approved(request))
}

#[cfg(test)]
mod test {
    use uuid::Uuid;

    use crate::organization::Organization;

    #[test]
    fn test_organization() {
        let mut org = Organization {
            id: Uuid::now_v7(),
            is_ai_data_processing_approved: Some(true),
        };

        assert_eq!(org.drop_if_not_ai_processing_approved(1), Some(1));
        assert_eq!(org.drop_if_not_ai_processing_approved(2), Some(2));

        org.is_ai_data_processing_approved = Some(false);
        assert_eq!(org.drop_if_not_ai_processing_approved(1), None);
        assert_eq!(org.drop_if_not_ai_processing_approved(2), None);

        org.is_ai_data_processing_approved = None;
        assert_eq!(org.drop_if_not_ai_processing_approved(1), None);
        assert_eq!(org.drop_if_not_ai_processing_approved(2), None);
    }
}
