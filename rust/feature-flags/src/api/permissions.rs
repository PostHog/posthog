use crate::flags::models::PersonalAPIKey;
use uuid::Uuid;
pub fn has_permission(
    personal_api_key: &PersonalAPIKey,
    scope_object: &str,
    required_scopes: &[&str], // or Vec<String>
) -> Result<(), String> {
    let key_scopes = &personal_api_key.scopes;

    // TRICKY: Legacy API keys have no scopes and are allowed to do anything, even if the view is unsupported.
    if key_scopes.is_empty() {
        return Ok(());
    }

    // If no required scopes, deny
    if required_scopes.is_empty() {
        return Err("This action does not support Personal API Key access".to_owned());
    }

    check_team_and_org_permissions(
        personal_api_key,
        personal_api_key.team_id,
        personal_api_key.organization_id,
        scope_object,
    )?;

    // Wildcard: allow everything
    if key_scopes.iter().any(|s| s == "*") {
        return Ok(());
    }

    // Check each required scope
    for required_scope in required_scopes {
        let has_scope = key_scopes.contains(&required_scope.to_string())
            || (required_scope.ends_with(":read")
                && key_scopes.contains(&required_scope.replace(":read", ":write")));
        if !has_scope {
            return Err(format!(
                "API key missing required scope '{}'",
                required_scope
            ));
        }
    }

    Ok(())
}

pub fn check_team_and_org_permissions(
    personal_api_key: &PersonalAPIKey,
    team_id: Option<i32>,
    organization_id: Uuid,
    scope_object: &str,
) -> Result<(), String> {
    if scope_object == "user" {
        return Ok(());
    }

    let scoped_teams = &personal_api_key.scoped_teams;
    match (scoped_teams.is_empty(), team_id) {
        (false, Some(id)) if !scoped_teams.contains(&id) => {
            return Err(format!(
                "API key does not have access to the requested project: ID {}.",
                id
            ));
        }
        (false, None) => {
            return Err(
                "API keys with scoped projects are only supported on project-based endpoints."
                    .to_owned(),
            );
        }
        _ => {}
    }

    let scoped_organizations = &personal_api_key.scoped_organizations;
    if !scoped_organizations.is_empty() {
        if !scoped_organizations.contains(&organization_id.to_string()) {
            return Err(format!(
                "API key does not have access to the requested organization: ID {}.",
                organization_id
            ));
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::models::PersonalAPIKey;
    use uuid::Uuid;
    fn make_key(
        scopes: Vec<String>,
        scoped_organizations: Vec<String>,
        scoped_teams: Vec<i32>,
        team_id: Option<i32>,
        organization_id: Uuid,
    ) -> PersonalAPIKey {
        PersonalAPIKey {
            id: "id".to_string(),
            label: "label".to_string(),
            value: None,
            secure_value: None,
            created_at: chrono::Utc::now(),
            last_used_at: None,
            team_id,
            organization_id,
            user_id: 1,
            scoped_organizations: scoped_organizations,
            scoped_teams: scoped_teams,
            scopes: scopes,
            mask_value: "mask".to_string(),
        }
    }

    #[test]
    fn allows_wildcard_scope() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(vec!["*".to_string()], vec![], vec![], Some(42), org_id);
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn allows_legacy_key() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(vec![], vec![], vec![], Some(42), org_id);
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn denies_missing_scope() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        let err = has_permission(&key, "feature_flag", &["feature_flag:write"]).unwrap_err();
        assert!(err.contains("API key missing required scope"));
    }

    #[test]
    fn denies_if_required_scopes_empty() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        let err = has_permission(&key, "feature_flag", &[]).unwrap_err();
        assert!(err.contains("does not support Personal API Key access"));
    }

    #[test]
    fn allows_read_scope() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec![
                "feature_flag:read".to_string(),
                "something_else:read".to_string(),
            ],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn allows_read_with_write_scope() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:write".to_string()],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn allows_read_scope_when_scoped_teams_matches() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![42, 1, 41],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn allows_read_scope_when_scoped_teams_empty() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn denies_read_scope_when_scoped_teams_does_not_match() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![23, 1, 41],
            Some(42),
            org_id,
        );
        let err = has_permission(&key, "feature_flag", &["feature_flag:write"]).unwrap_err();
        assert!(err.contains("API key does not have access to the requested project: ID 42."));
    }

    #[test]
    fn allows_read_scope_when_scoped_orgs_matches() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![org_id.to_string()],
            vec![],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn allows_read_scope_when_scoped_orgs_empty() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![],
            vec![],
            Some(42),
            org_id,
        );
        assert!(has_permission(&key, "feature_flag", &["feature_flag:read"]).is_ok());
    }

    #[test]
    fn denies_read_scope_when_scoped_orgs_does_not_match() {
        let org_id = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();
        let org_id2 = "123e4567-e89b-12d3-a456-426614174001";
        let key = make_key(
            vec!["feature_flag:read".to_string()],
            vec![org_id2.to_string()],
            vec![],
            Some(42),
            org_id,
        );
        let err = has_permission(&key, "feature_flag", &["feature_flag:write"]).unwrap_err();
        assert!(err.contains("API key does not have access to the requested organization: ID 123e4567-e89b-12d3-a456-426614174000."));
    }
}
