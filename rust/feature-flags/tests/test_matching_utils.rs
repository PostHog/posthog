use anyhow::Result;
use feature_flags::flags::flag_matching_utils::calculate_hash;

pub mod common;

#[tokio::test]
async fn calc_some_hashes() -> anyhow::Result<()> {
    assert_eq!(0.4525525406521796, calculate_hash("12312", "", "").unwrap());
    assert_eq!(0.5467118336624435, calculate_hash("32132", "", "").unwrap());
    assert_eq!(0.8015364780087316, calculate_hash("PostHog", "", "").unwrap());
    Ok(())
}