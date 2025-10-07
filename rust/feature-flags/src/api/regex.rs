use std::collections::{HashMap, HashSet};

use axum::{debug_handler, Json};
use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub(crate) struct RegexRequest {
    patterns: Vec<String>,
}

#[derive(Debug, Serialize)]
pub(crate) struct RegexResponse {
    // Map of pattern to error message
    errors: HashMap<String, String>,
}

#[inline]
fn get_regex_error_message(err: regex::Error) -> String {
    let error_str = err.to_string();
    let message = error_str
        .split("error: ")
        .last()
        .unwrap_or(&error_str)
        .trim();
    return message.to_string();
}

#[debug_handler]
pub(crate) async fn regex_validate_handler(Json(req): Json<RegexRequest>) -> Json<RegexResponse> {
    let RegexRequest { patterns } = req;

    let unique_patterns: HashSet<_> = patterns.into_iter().collect();
    let errors: HashMap<_, _> = unique_patterns
        .into_iter()
        .filter_map(|pattern| {
            Regex::new(&pattern)
                .err()
                .map(|e| (pattern, get_regex_error_message(e)))
        })
        .collect();

    Json(RegexResponse { errors })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_regex_error_message_extracts_message() {
        let result = Regex::new("(unclosed");
        assert!(result.is_err());
        let error_msg = get_regex_error_message(result.unwrap_err());
        assert!(error_msg.contains("unclosed group"));
    }

    #[test]
    fn test_get_regex_error_message_handles_no_prefix() {
        let result = Regex::new("(?P<>invalid)");
        assert!(result.is_err());
        let error_msg = get_regex_error_message(result.unwrap_err());
        assert!(!error_msg.is_empty());
    }

    #[tokio::test]
    async fn test_regex_validate_handler_valid_patterns() {
        let request = RegexRequest {
            patterns: vec!["^hello$".to_string(), "world.*".to_string()],
        };
        let response = regex_validate_handler(Json(request)).await;
        assert!(response.errors.is_empty());
    }

    #[tokio::test]
    async fn test_regex_validate_handler_invalid_patterns() {
        let request = RegexRequest {
            patterns: vec!["(unclosed".to_string(), "[invalid".to_string()],
        };
        let response = regex_validate_handler(Json(request)).await;
        assert_eq!(response.errors.len(), 2);
        assert!(response.errors.contains_key("(unclosed"));
        assert!(response.errors.contains_key("[invalid"));
    }

    #[tokio::test]
    async fn test_regex_validate_handler_mixed_patterns() {
        let request = RegexRequest {
            patterns: vec![
                "^valid$".to_string(),
                "(invalid".to_string(),
                "also.*valid".to_string(),
            ],
        };
        let response = regex_validate_handler(Json(request)).await;
        assert_eq!(response.errors.len(), 1);
        assert!(response.errors.contains_key("(invalid"));
    }

    #[tokio::test]
    async fn test_regex_validate_handler_deduplicates_patterns() {
        let request = RegexRequest {
            patterns: vec![
                "(invalid".to_string(),
                "(invalid".to_string(),
                "(invalid".to_string(),
            ],
        };
        let response = regex_validate_handler(Json(request)).await;
        assert_eq!(response.errors.len(), 1);
        assert!(response.errors.contains_key("(invalid"));
    }

    #[tokio::test]
    async fn test_regex_validate_handler_empty_patterns() {
        let request = RegexRequest { patterns: vec![] };
        let response = regex_validate_handler(Json(request)).await;
        assert!(response.errors.is_empty());
    }
}
