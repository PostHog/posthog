use crate::error::VmError;

pub fn like(
    val: impl AsRef<str>,
    pattern: impl AsRef<str>,
    case_sensitive: bool,
) -> Result<bool, VmError> {
    Err(VmError::NotImplemented("like".to_string()))
}

pub fn regex_match(
    val: impl AsRef<str>,
    pattern: impl AsRef<str>,
    case_sensitive: bool,
) -> Result<bool, VmError> {
    Err(VmError::NotImplemented("regex_match".to_string()))
}
