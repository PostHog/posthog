use crate::flags::flag_models::FlagPropertyGroup;

impl FlagPropertyGroup {
    /// Returns true if the group is rolled out to some percentage greater than 0.0
    pub fn is_rolled_out_to_to_some(&self) -> bool {
        self.rollout_percentage.is_some() && self.rollout_percentage.unwrap() > 0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(Some(100.0), true)]
    #[case(Some(1.0), true)]
    #[case(Some(0.0), false)]
    #[case(None, false)]
    fn test_is_rolled_out_to_to_some(
        #[case] rollout_percentage: Option<f64>,
        #[case] expected: bool,
    ) {
        let group = FlagPropertyGroup {
            properties: None,
            rollout_percentage,
            variant: None,
        };
        assert_eq!(group.is_rolled_out_to_to_some(), expected);
    }
}
