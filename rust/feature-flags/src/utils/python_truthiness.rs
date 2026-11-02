use serde_json::Value;

/// Mirrors Python truthiness for a JSON value, for code that matches a Python `x or default`
/// read: null, false, zero, and an empty string, array or object are falsy.
pub fn is_falsy(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::Bool(b) => !b,
        Value::Number(n) => n.as_f64() == Some(0.0),
        Value::String(s) => s.is_empty(),
        Value::Array(a) => a.is_empty(),
        Value::Object(o) => o.is_empty(),
    }
}

#[cfg(test)]
mod tests {
    use super::is_falsy;
    use serde_json::json;

    #[test]
    fn is_falsy_matches_python_truthiness() {
        assert!(is_falsy(&json!(null)));
        assert!(is_falsy(&json!(false)));
        assert!(is_falsy(&json!(0)));
        assert!(is_falsy(&json!(0.0)));
        assert!(is_falsy(&json!("")));
        assert!(is_falsy(&json!([])));
        assert!(is_falsy(&json!({})));
        // Truthy values pass through.
        assert!(!is_falsy(&json!(true)));
        assert!(!is_falsy(&json!(1)));
        assert!(!is_falsy(&json!("x")));
        assert!(!is_falsy(&json!([1])));
        assert!(!is_falsy(&json!({"k": "v"})));
    }
}
