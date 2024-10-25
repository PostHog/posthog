use crate::{api::FlagError, config::TeamIdsToTrack};

pub fn team_id_label_filter(
    team_ids_to_track: TeamIdsToTrack,
) -> impl Fn(&[(String, String)]) -> Vec<(String, String)> {
    move |labels: &[(String, String)]| {
        labels
            .iter()
            .map(|(key, value)| {
                if key == "team_id" {
                    match value.parse::<i32>() {
                        Ok(team_id) => {
                            let filtered_value = match &team_ids_to_track {
                                TeamIdsToTrack::All => value.clone(),
                                TeamIdsToTrack::TeamIds(ids) => {
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
        FlagError::DatabaseError(msg) => {
            if msg.contains("statement timeout") {
                "timeout"
            } else if msg.contains("no more connections") {
                "no_more_connections"
            } else if msg.contains("Failed to fetch conditions") {
                "flag_condition_retry"
            } else if msg.contains("Failed to fetch group") {
                "group_mapping_retry"
            } else if msg.contains("Database healthcheck failed") {
                "healthcheck_failed"
            } else if msg.contains("query_wait_timeout") {
                "query_wait_timeout"
            } else {
                "database_error"
            }
        }
        FlagError::DatabaseUnavailable => "database_unavailable",
        FlagError::RedisUnavailable => "redis_unavailable",
        FlagError::TimeoutError => "timeout_error",
        FlagError::NoGroupTypeMappings => "no_group_type_mappings",
        _ => "unknown",
    }
}

#[cfg(test)]
#[test]
fn test_all_team_ids_pass_through() {
    let filter = team_id_label_filter(TeamIdsToTrack::All);

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
    let filter = team_id_label_filter(TeamIdsToTrack::TeamIds(vec![123]));

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
    let filter = team_id_label_filter(TeamIdsToTrack::TeamIds(vec![456]));

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
    let filter = team_id_label_filter(TeamIdsToTrack::TeamIds(vec![123]));

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
    let filter = team_id_label_filter(TeamIdsToTrack::TeamIds(vec![123]));

    let labels = vec![
        ("env".to_string(), "production".to_string()),
        ("version".to_string(), "1.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}

#[test]
fn test_multiple_team_ids() {
    let filter = team_id_label_filter(TeamIdsToTrack::TeamIds(vec![123, 456]));

    let labels = vec![
        ("env".to_string(), "staging".to_string()),
        ("team_id".to_string(), "456".to_string()),
        ("version".to_string(), "2.0".to_string()),
    ];

    let filtered_labels = filter(&labels);

    assert_eq!(filtered_labels, labels);
}
