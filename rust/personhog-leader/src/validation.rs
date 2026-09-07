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
