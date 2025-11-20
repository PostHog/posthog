//! Cleanup utility for test databases
//! Run after tests to clean up all test data
//!
//! Usage:
//!   cargo run --bin cleanup-test-db
//!   # Or after tests:
//!   cargo test && cargo run --bin cleanup-test-db

use feature_flags::config::Config;
use feature_flags::utils::test_utils::TestContext;

#[tokio::main]
async fn main() {
    println!("🧹 Cleaning up test databases...");

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    match context.cleanup_all_test_data().await {
        Ok(_) => {
            println!("✅ Test databases cleaned successfully!");
        }
        Err(e) => {
            eprintln!("❌ Failed to cleanup test databases: {}", e);
            std::process::exit(1);
        }
    }
}
