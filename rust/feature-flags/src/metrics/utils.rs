use crate::{api::errors::FlagError, config::TeamIdCollection, utils::graph_utils::DependencyType};

pub fn team_id_label_filter(
    team_ids_to_track: TeamIdCollection,
) -> impl Fn(&[(String, String)]) -> Vec<(String, String)> {
    move |labels: &[(String, String)]| {
        labels
            .iter()
            .map(|(key, value)| {
                if key == "team_id" {
                    match value.parse::<i32>() {
                        Ok(team_id) => {
                            let filtered_value = match &team_ids_to_track {
                                TeamIdCollection::All => value.clone(),
                                TeamIdCollection::None => "none".to_string(),
                                TeamIdCollection::TeamIds(ids) => {
                                    if ids.contains(&team_id) {
                                        value.clone()
                                    } else {
                                        "unknown".to_string()
                                    }
                                }
                            };
                            (key.clone(), filtered_value)
                        }
                        Err(_) => (key.clone(), "unknown".to_string()),
                    }
                } else {
                    (key.clone(), value.clone())
                }
            })
            .collect()
    }
}

pub fn parse_exception_for_prometheus_label(err: &FlagError) -> &'static str {
    match err {
        FlagError::DatabaseError(sqlx_error, context) => {
            let error_msg = sqlx_error.to_string();
            let context_msg = context.as_deref().unwrap_or("");

            if error_msg.contains("statement timeout") {
                "timeout"
            } else if error_msg.contains("no more connections") {
                "no_more_connections"
            } else if context_msg.contains("Failed to fetch conditions") {
                "flag_condition_retry"
            } else if context_msg.contains("Failed to fetch group") {
                "group_mapping_retry"
            } else if context_msg.contains("Database healthcheck failed") {
                "healthcheck_failed"
            } else if error_msg.contains("query_wait_timeout") {
                "query_wait_timeout"
            } else {
                "database_error"
            }
        }
        FlagError::DatabaseUnavailable => "database_unavailable",
        FlagError::RedisUnavailable => "redis_unavailable",
        FlagError::TimeoutError(ref timeout_type) => {
            match timeout_type {
                Some(ref timeout_type) => {
                    // Return timeout type with "timeout:" prefix for granular metrics
                    Box::leak(format!("timeout:{timeout_type}").into_boxed_str())
                }
                None => "timeout_error",
            }
        }
        FlagError::NoGroupTypeMappings => "no_group_type_mappings",
        FlagError::DependencyNotFound(dependency_type, _) => match dependency_type {
            DependencyType::Cohort => "dependency_not_found_cohort",
            DependencyType::Flag => "dependency_not_found_flag",
        },
        FlagError::DependencyCycle(dependency_type, _) => match dependency_type {
            DependencyType::Cohort => "dependency_cycle_cohort",
            DependencyType::Flag => "dependency_cycle_flag",
        },
        _ => "unknown",
    }
}

#[cfg(test)]
#[test]
fn test_all_team_ids_pass_through() {
    let filter = team_id_label_filter(TeamIdCollection::All);

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "123".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}

#[test]
fn test_specific_team_id_matches() {
    let filter = team_id_label_filter(TeamIdCollection::TeamIds(vec![123]));

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "123".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}

#[test]
fn test_specific_team_id_does_not_match() {
    let filter = team_id_label_filter(TeamIdCollection::TeamIds(vec![456]));

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "123".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let expected_labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "unknown".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, expected_labels);
}

#[test]
fn test_invalid_team_id_value() {
    let filter = team_id_label_filter(TeamIdCollection::TeamIds(vec![123]));

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "abc".to_string()), // Invalid team_id
        ("version".to_string(), "1.0".to_string()),
    ];

    let expected_labels = vec![
        ("env".to_string(), "production".to_string()),
        ("team_id".to_string(), "unknown".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, expected_labels);
}

#[test]
fn test_missing_team_id_label() {
    let filter = team_id_label_filter(TeamIdCollection::TeamIds(vec![123]));

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}

#[test]
fn test_multiple_team_ids() {
    let filter = team_id_label_filter(TeamIdCollection::TeamIds(vec![123, 456]));

    let labels = vec![
        ("env".to_string(), "staging".to_string()),
        ("team_id".to_string(), "456".to_string()),
        ("version".to_string(), "2.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}

#[test]
fn test_timeout_error_prometheus_labels() {
    // Test generic timeout error
    let timeout_error = FlagError::TimeoutError(None);
    assert_eq!(
        parse_exception_for_prometheus_label(&timeout_error),
        "timeout_error"
    );

    // Test specific timeout types
    let query_canceled_error = FlagError::TimeoutError(Some("query_canceled".to_string()));
    assert_eq!(
        parse_exception_for_prometheus_label(&query_canceled_error),
        "timeout:query_canceled"
    );

    let lock_timeout_error = FlagError::TimeoutError(Some("lock_not_available".to_string()));
    assert_eq!(
        parse_exception_for_prometheus_label(&lock_timeout_error),
        "timeout:lock_not_available"
    );

    let pool_timeout_error = FlagError::TimeoutError(Some("pool_timeout".to_string()));
    assert_eq!(
        parse_exception_for_prometheus_label(&pool_timeout_error),
        "timeout:pool_timeout"
    );

    let client_timeout_error = FlagError::TimeoutError(Some("client_timeout".to_string()));
    assert_eq!(
        parse_exception_for_prometheus_label(&client_timeout_error),
        "timeout:client_timeout"
    );

    // Test unknown timeout type
    let unknown_timeout_error = FlagError::TimeoutError(Some("unknown_type".to_string()));
    assert_eq!(
        parse_exception_for_prometheus_label(&unknown_timeout_error),
        "timeout:unknown_type"
    );
}
