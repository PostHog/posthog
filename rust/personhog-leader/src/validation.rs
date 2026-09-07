use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum ValidationError {
    #[error("Invalid UUID format")]
    InvalidUuid,

    #[error("Invalid JSON format: {0}")]
    InvalidJson(String),

    #[error("Properties size ({actual} bytes) exceeds limit ({max} bytes)")]
    PropertiesTooLarge { actual: usize, max: usize },
}

pub fn validate_before_publish(
    uuid: &str,
    properties: &[u8],
    max_properties_bytes: usize,
) -> Result<(), ValidationError> {
    if properties.len() > max_properties_bytes {
        return Err(ValidationError::PropertiesTooLarge {
            actual: properties.len(),
            max: max_properties_bytes,
        });
    }
    validate_uuid(uuid)?;
    validate_json_object(properties)?;

    Ok(())
}

fn validate_uuid(uuid: &str) -> Result<(), ValidationError> {
    Uuid::parse_str(uuid).map_err(|_| ValidationError::InvalidUuid)?;
    Ok(())
}

/// Verify that `properties` is a well-formed JSON object (`{...}`).
fn validate_json_object(properties: &[u8]) -> Result<(), ValidationError> {
    serde_json::from_slice::<serde_json::Map<String, serde_json::Value>>(properties)
        .map(|_| ())
        .map_err(|e| ValidationError::InvalidJson(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID_UUID: &str = "550e8400-e29b-41d4-a716-446655440000";
    const NO_LIMIT: usize = usize::MAX;

    #[test]
    fn valid_record_passes() {
        let props = b"{\"$os\": \"Linux\"}";
        assert!(validate_before_publish(VALID_UUID, props, NO_LIMIT).is_ok());
    }

    #[test]
    fn empty_object_passes() {
        assert!(validate_before_publish(VALID_UUID, b"{}", NO_LIMIT).is_ok());
    }

    #[test]
    fn nested_properties_pass() {
        let props = b"{\"plan\": \"enterprise\", \"seats\": 42}";
        assert!(validate_before_publish(VALID_UUID, props, NO_LIMIT).is_ok());
    }

    #[test]
    fn invalid_uuid_rejected() {
        let err = validate_before_publish("not-a-uuid", b"{}", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidUuid));
    }

    #[test]
    fn empty_uuid_rejected() {
        let err = validate_before_publish("", b"{}", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidUuid));
    }

    #[test]
    fn non_json_rejected() {
        let err = validate_before_publish(VALID_UUID, b"not json", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidJson(_)));
    }

    #[test]
    fn json_array_rejected() {
        // Valid JSON but not an object, the writer's upsert expects a map.
        let err = validate_before_publish(VALID_UUID, b"[1, 2, 3]", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidJson(_)));
    }

    #[test]
    fn json_string_rejected() {
        let err = validate_before_publish(VALID_UUID, b"\"hello\"", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidJson(_)));
    }

    #[test]
    fn json_null_rejected() {
        let err = validate_before_publish(VALID_UUID, b"null", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidJson(_)));
    }

    #[test]
    fn non_utf8_bytes_rejected() {
        // Properties that aren't valid UTF-8 can't be valid JSON.
        let err = validate_before_publish(VALID_UUID, b"\xff\xfe", NO_LIMIT).unwrap_err();
        assert!(matches!(err, ValidationError::InvalidJson(_)));
    }

    #[test]
    fn properties_at_limit_pass() {
        let props = b"{\"k\": \"v\"}";
        assert!(validate_before_publish(VALID_UUID, props, props.len()).is_ok());
    }

    #[test]
    fn properties_one_byte_over_limit_rejected() {
        let props = b"{\"k\": \"v\"}";
        let err = validate_before_publish(VALID_UUID, props, props.len() - 1).unwrap_err();
        assert!(matches!(
            err,
            ValidationError::PropertiesTooLarge { actual, max }
            if actual == props.len() && max == props.len() - 1
        ));
    }

    #[test]
    fn size_check_runs_before_json_parse() {
        // Oversized *and* invalid JSON, size error should win.
        let junk = vec![b'x'; 10];
        let err = validate_before_publish(VALID_UUID, &junk, 5).unwrap_err();
        assert!(matches!(err, ValidationError::PropertiesTooLarge { .. }));
    }
}
