use crate::api::errors::FlagError;
use crate::flags::flag_models::MultivariateFlagVariant;

pub fn is_in_rollout(hash: f64, percentage: f64) -> bool {
    percentage == 100.0 || hash <= percentage / 100.0
}

pub(crate) fn rollout_with_hash(
    percentage: f64,
    hash: impl FnOnce() -> Result<f64, FlagError>,
) -> Result<bool, FlagError> {
    // Identifier resolution and hashing must remain lazy at 100%.
    if percentage == 100.0 {
        return Ok(true);
    }
    Ok(is_in_rollout(hash()?, percentage))
}

pub fn select_variant(hash: f64, variants: &[MultivariateFlagVariant]) -> Option<&str> {
    let mut cumulative_percentage = 0.0;
    for variant in variants {
        cumulative_percentage += variant.rollout_percentage / 100.0;
        if hash < cumulative_percentage {
            return Some(&variant.key);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_rollout_bypasses_hash_errors() {
        let hash_error = || Err(FlagError::HashKeyOverrideError);
        assert!(rollout_with_hash(100.0, hash_error).unwrap());
        assert!(matches!(
            rollout_with_hash(99.0, hash_error),
            Err(FlagError::HashKeyOverrideError)
        ));
        assert!(rollout_with_hash(100.0, || panic!("must not hash")).unwrap());
    }

    #[test]
    fn incomplete_variant_weights_leave_the_remainder_unassigned() {
        let variants = [MultivariateFlagVariant {
            key: "control".to_string(),
            rollout_percentage: 40.0,
            ..Default::default()
        }];
        assert_eq!(select_variant(0.4, &variants), None);
        assert_eq!(select_variant(1.0, &variants), None);
    }
}
