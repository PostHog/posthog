use crate::config::TeamIdCollection;

#[cfg(test)]
use crate::api::errors::FlagError;

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
fn test_timeout_error_evaluation_error_codes() {
    // Generic timeout without a specific type
    let timeout_error = FlagError::TimeoutError(None);
    assert_eq!(timeout_error.evaluation_error_code(), "timeout_error");

    // Specific timeout types get "timeout:<type>" granularity
    let query_canceled_error = FlagError::TimeoutError(Some("query_canceled".to_string()));
    assert_eq!(
        query_canceled_error.evaluation_error_code(),
        "timeout:query_canceled"
    );

    let lock_timeout_error = FlagError::TimeoutError(Some("lock_not_available".to_string()));
    assert_eq!(
        lock_timeout_error.evaluation_error_code(),
        "timeout:lock_not_available"
    );

    let pool_timeout_error = FlagError::TimeoutError(Some("pool_timeout".to_string()));
    assert_eq!(
        pool_timeout_error.evaluation_error_code(),
        "timeout:pool_timeout"
    );

    let client_timeout_error = FlagError::TimeoutError(Some("client_timeout".to_string()));
    assert_eq!(
        client_timeout_error.evaluation_error_code(),
        "timeout:client_timeout"
    );

    let unknown_timeout_error = FlagError::TimeoutError(Some("unknown_type".to_string()));
    assert_eq!(
        unknown_timeout_error.evaluation_error_code(),
        "timeout:unknown_type"
    );
}
