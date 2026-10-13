//! Checks against a live ClickHouse that the run breaker classifies a scan the server stops after
//! rows have flowed. The client reads no error code then, so only a real response shows the shape.

#![cfg(feature = "ch-test-support")]

use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::ResourceError;
use cohort_seeder::config::Config;
use envconfig::Envconfig;

#[tokio::test]
async fn a_resource_error_raised_mid_stream_reaches_the_breaker() {
    let client = build_client(&Config::init_from_env().expect("the seeder config has defaults"))
        .expect("the default ClickHouse client builds");
    let memory = "SELECT number FROM numbers(10000000) WHERE throwIf(number = 5000000, 'test', toInt32(241)) = 0";
    for (sql, settings, expected) in [
        (
            memory,
            [
                ("allow_custom_error_code_in_throwif", "1"),
                ("max_threads", "1"),
            ],
            ResourceError::MemoryLimitExceeded,
        ),
        (
            "SELECT number FROM system.numbers",
            [("max_execution_time", "1"), ("max_threads", "1")],
            ResourceError::TimeoutExceeded,
        ),
    ] {
        let query = settings
            .into_iter()
            .fold(client.query(sql), |query, (name, value)| {
                query.with_option(name, value)
            });
        let mut cursor = query.fetch::<u64>().expect("the query builds");
        let mut rows = 0_u64;
        let error = loop {
            match cursor.next().await {
                Ok(Some(_)) => rows += 1,
                Ok(None) => panic!("{sql}: finished without an error"),
                Err(error) => break error,
            }
        };
        assert!(
            rows > 0,
            "{sql}: failed before any row, so nothing was streamed"
        );
        let classified = ResourceError::classify(&error);
        assert!(
            classified == Some(expected) || classified == Some(ResourceError::ResponseCut),
            "{sql}: {error:?} classified as {classified:?}"
        );
    }
}
